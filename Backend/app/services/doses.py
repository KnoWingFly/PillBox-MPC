"""Dose rows (telemetry_logs with a status) and their notifications.

A dose is identified by (schedule_id, scheduled_for); the partial unique
index telemetry_logs_dose_key_idx guarantees one row per dose, so telemetry
ingestion and the rules engine can both "get or create" it safely.
"""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Executable, and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Elderly, Notification, Schedule, TelemetryLog
from app.models.enums import DoseStatus, NotificationType, Severity
from app.services.adherence import DoseInstants
from app.services.notifications import NotificationSpec, notify
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


def dose_insert_stmt(
    device_id: UUID,
    elderly_id: UUID | None,
    schedule: Schedule,
    inst: DoseInstants,
    event_type: str,
) -> Executable:
    """INSERT ... ON CONFLICT DO NOTHING for a PENDING dose row."""
    return (
        insert(TelemetryLog)
        .values(
            device_id=device_id,
            elderly_id=elderly_id,
            schedule_id=schedule.id,
            slot_number=schedule.slot_number,
            event_type=event_type,
            status=DoseStatus.PENDING.value,
            scheduled_date=inst.scheduled_date,
            scheduled_for=inst.scheduled_for,
            deadline_at=inst.deadline_at,
            recorded_at=inst.scheduled_for,
        )
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
    """Returns the dose row, locked FOR UPDATE for the rest of the transaction."""
    await session.execute(dose_insert_stmt(device_id, elderly_id, schedule, inst, event_type))
    row = await session.execute(
        select(TelemetryLog)
        .where(TelemetryLog.schedule_id == schedule.id, TelemetryLog.scheduled_for == inst.scheduled_for)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return row.scalar_one()


async def elderly_display_name(session: AsyncSession, elderly_id: UUID) -> str:
    row = await session.execute(select(Elderly.nickname, Elderly.full_name).where(Elderly.id == elderly_id))
    found = row.first()
    if found is None:
        return "-"
    nickname, full_name = found
    return nickname or full_name


async def notify_dose(
    session: AsyncSession, log: TelemetryLog, ntype: NotificationType, tz: ZoneInfo
) -> list[UUID]:
    if log.elderly_id is None or log.slot_number is None:
        return []
    severity = {
        NotificationType.DOSE_MISSED: Severity.CRITICAL,
        NotificationType.DOSE_LATE: Severity.WARNING,
        NotificationType.DOSE_TAKEN: Severity.INFO,
    }[ntype]
    scheduled = log.scheduled_for.astimezone(tz).strftime("%H:%M") if log.scheduled_for else "-"
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
                "elderly": await elderly_display_name(session, log.elderly_id),
                "delay": log.delay_minutes or 0,
            },
        ),
    )


async def auto_resolve_missed(session: AsyncSession, log_id: UUID, now: datetime, note: str) -> None:
    """A dose first decided MISSED and later proven TAKEN: close the open
    DOSE_MISSED notifications for it (resolved_by_user_id stays NULL = system)."""
    await session.execute(
        update(Notification)
        .where(
            Notification.event_key == f"{NotificationType.DOSE_MISSED.value}:{log_id}",
            Notification.is_resolved.is_(False),
        )
        .values(is_resolved=True, resolved_at=now, resolution_note=note)
    )
