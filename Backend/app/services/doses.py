"""Dose rows (telemetry_logs with a status) and their notifications.

A dose is identified by (schedule_id, scheduled_for); the partial unique
index telemetry_logs_dose_key_idx guarantees one row per dose, so telemetry
ingestion and the rules engine can both "get or create" it safely.
"""

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Executable, and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, Schedule, TelemetryLog
from app.models.enums import DoseStatus, NotificationType, Severity
from app.services.adherence import DoseInstants
from app.services.notifications import NotificationSpec, load_recipients, notify
from app.services.slots import slot_layout

_DOSE_KEY_WHERE = and_(TelemetryLog.schedule_id.is_not(None), TelemetryLog.scheduled_for.is_not(None))

_PERIOD_LABELS = {
    "MORNING": ("Pagi", "morning"),
    "AFTERNOON": ("Siang", "afternoon"),
    "EVENING": ("Sore", "evening"),
    "NIGHT": ("Malam", "night"),
}


def slot_label(slot_number: int) -> str:
    """Mobile app slot id: A1..A4, B1..B4."""
    layout = slot_layout(slot_number)
    return f"{layout.row.value}{(slot_number - 1) % 4 + 1}"


def period_label(slot_number: int) -> dict[str, str]:
    layout = slot_layout(slot_number)
    id_period, en_period = _PERIOD_LABELS[layout.day_period.value]
    before = layout.row.value == "A"
    return {
        "ID": f"{id_period}, {'Sebelum' if before else 'Sesudah'} Makan",
        "EN": f"{en_period}, {'before' if before else 'after'} meal",
    }


def pending_dose_row(
    device_id: UUID,
    elderly_id: UUID | None,
    schedule: Schedule,
    inst: DoseInstants,
    event_type: str,
) -> dict[str, Any]:
    """Column values of a PENDING dose row."""
    return {
        "device_id": device_id,
        "elderly_id": elderly_id,
        "schedule_id": schedule.id,
        "slot_number": schedule.slot_number,
        "event_type": event_type,
        "status": DoseStatus.PENDING.value,
        "scheduled_date": inst.scheduled_date,
        "scheduled_for": inst.scheduled_for,
        "deadline_at": inst.deadline_at,
        "recorded_at": inst.scheduled_for,
    }


def pending_doses_insert_stmt(rows: list[dict[str, Any]]) -> Executable:
    """Multi-row INSERT ... ON CONFLICT DO NOTHING RETURNING id for PENDING
    dose rows (rows from pending_dose_row). Only newly created ids come back."""
    return (
        insert(TelemetryLog)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=[TelemetryLog.schedule_id, TelemetryLog.scheduled_for],
            index_where=_DOSE_KEY_WHERE,
        )
        .returning(TelemetryLog.id)
    )


async def get_or_create_dose(
    session: AsyncSession,
    device_id: UUID,
    elderly_id: UUID | None,
    schedule: Schedule,
    inst: DoseInstants,
    event_type: str,
) -> TelemetryLog:
    """Returns the dose row, locked for the rest of the transaction.

    One round trip: INSERT ... ON CONFLICT DO UPDATE locks and returns the
    existing row (the no-op SET only exists to make RETURNING yield it),
    exactly like the former INSERT followed by SELECT ... FOR UPDATE."""
    row_values = pending_dose_row(device_id, elderly_id, schedule, inst, event_type)
    stmt = insert(TelemetryLog).values(row_values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[TelemetryLog.schedule_id, TelemetryLog.scheduled_for],
        index_where=_DOSE_KEY_WHERE,
        set_={"schedule_id": stmt.excluded.schedule_id},
    ).returning(TelemetryLog)
    row = await session.execute(
        select(TelemetryLog).from_statement(stmt).execution_options(populate_existing=True)
    )
    return row.scalar_one()


# What the app may offer on an open DOSE_MISSED notification (see services/late_dose.py).
MISSED_DOSE_ACTIONS = ["LATE_RELEASE", "CONFIRM_TAKEN"]


async def notify_dose(
    session: AsyncSession, log: TelemetryLog, ntype: NotificationType, tz: ZoneInfo, *, variant: str | None = None
) -> list[UUID]:
    if log.elderly_id is None or log.slot_number is None:
        return []
    severity = {
        NotificationType.DOSE_MISSED: Severity.CRITICAL,
        NotificationType.DOSE_LATE: Severity.WARNING,
        NotificationType.DOSE_TAKEN: Severity.INFO,
    }[ntype]
    recipients = await load_recipients(session, log.elderly_id)
    if not recipients:
        return []
    scheduled = log.scheduled_for.astimezone(tz).strftime("%H:%M") if log.scheduled_for else "-"
    taken = log.recorded_at.astimezone(tz).strftime("%H:%M") if log.recorded_at else "-"
    return await notify(
        session,
        NotificationSpec(
            type=ntype,
            severity=severity,
            event_key=f"{ntype.value}:{log.id}",
            elderly_id=log.elderly_id,
            device_id=log.device_id,
            telemetry_log_id=log.id,
            params={
                "slot": slot_label(log.slot_number),
                "period": period_label(log.slot_number),
                "time": scheduled,
                "elderly": recipients[0].elderly_name,
                "delay": log.delay_minutes or 0,
                "taken": taken,
            },
            slot_number=log.slot_number,
            delay_minutes=log.delay_minutes,
            variant=variant,
            actions=MISSED_DOSE_ACTIONS if ntype is NotificationType.DOSE_MISSED else [],
        ),
        recipients=recipients,
    )


async def auto_resolve_missed(session: AsyncSession, log_id: UUID, now: datetime, note: str) -> None:
    """A dose first decided MISSED and later proven TAKEN: close the open
    DOSE_MISSED notifications for it, and a forced-open alert linked to it
    (resolved_by_user_id stays NULL = system). They stay in history, resolved."""
    await session.execute(
        update(Notification)
        .where(
            Notification.telemetry_log_id == log_id,
            Notification.type.in_([NotificationType.DOSE_MISSED.value, NotificationType.UNSCHEDULED_OPEN.value]),
            Notification.is_resolved.is_(False),
        )
        .values(is_resolved=True, resolved_at=now, resolution_note=note)
    )


async def report_taken_after_missed(
    session: AsyncSession, log: TelemetryLog, tz: ZoneInfo, now: datetime, how: str
) -> None:
    """The dose was MISSED and is now TAKEN (log already updated and flushed): close the
    missed alert with a note and tell every caregiver it was taken after all, so whoever
    was alarmed knows it is settled. `how` ends the note, e.g. "lewat sensor pillbox"."""
    taken = log.recorded_at.astimezone(tz).strftime("%H:%M") if log.recorded_at else "-"
    note = f"Diminum terlambat pukul {taken} (+{log.delay_minutes or 0} menit), {how}."
    await auto_resolve_missed(session, log.id, now, note)
    await notify_dose(session, log, NotificationType.DOSE_LATE, tz, variant="AFTER_MISSED")


async def forget_dose(session: AsyncSession, log: TelemetryLog, now: datetime, note: str) -> None:
    """Removes a decided dose row so it can be recorded again from scratch (its open alerts are
    resolved with `note` first; other notifications and device_events keep their history, unlinked)."""
    await session.execute(
        update(Notification)
        .where(Notification.telemetry_log_id == log.id, Notification.is_resolved.is_(False))
        .values(is_resolved=True, resolved_at=now, resolution_note=note)
    )
    await session.delete(log)
    await session.flush()
