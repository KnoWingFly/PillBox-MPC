"""Adherence journal: calendar, daily timeline, period summary, and manual
confirmation. Dates are the dose's local date in the device timezone
(telemetry_logs.scheduled_date)."""

import calendar as pycal
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import conflict, not_found, unprocessable
from app.models import Device, Notification, Schedule, TelemetryLog, User
from app.models.enums import (
    ALL_ROLES,
    EDITOR_ROLES,
    EVENT_MANUAL_CONFIRMATION,
    DoseStatus,
    JournalStatus,
    LogSource,
)
from app.schemas.journal import (
    CalendarDay,
    CalendarOut,
    DayOut,
    DoseCard,
    ManualConfirmationIn,
    ManualConfirmationOut,
    SummaryOut,
)
from app.services.access import require_role
from app.services.adherence import AdherenceSummary, delay_minutes_for, dose_instants, is_scheduled_on, journal_status
from app.services.doses import auto_resolve_missed
from app.services.slots import slot_layout
from app.services.timeutil import as_aware, zone

logger = logging.getLogger(__name__)

MAX_SUMMARY_DAYS = 366


@dataclass
class DoseRecord:
    log: TelemetryLog | None
    device: Device
    schedule: Schedule | None
    slot_number: int
    scheduled_for: datetime
    status: JournalStatus


async def _elderly_devices(session: AsyncSession, elderly_id: UUID) -> list[Device]:
    rows = await session.execute(select(Device).where(Device.elderly_id == elderly_id))
    return list(rows.scalars().all())


async def day_doses(
    session: AsyncSession,
    elderly_id: UUID,
    devices: list[Device],
    day_for: dict[UUID, date],
    now: datetime,
    unlinked_date: date | None = None,
) -> list[DoseRecord]:
    """Dose rows for each device's date, plus not-yet-materialized doses that
    are still upcoming (dose_log_id = null, status PENDING). day_for maps
    device_id -> local date to show for that device. With unlinked_date, rows
    of devices no longer linked to this elderly (history) on that date are
    included too."""
    records: list[DoseRecord] = []
    devices_by_id = {d.id: d for d in devices}
    dates = set(day_for.values()) | ({unlinked_date} if unlinked_date else set())
    if not dates:
        return records
    rows = await session.execute(
        select(TelemetryLog, Device, Schedule)
        .join(Device, Device.id == TelemetryLog.device_id)
        .outerjoin(Schedule, Schedule.id == TelemetryLog.schedule_id)
        .where(
            TelemetryLog.elderly_id == elderly_id,
            TelemetryLog.status.is_not(None),
            TelemetryLog.scheduled_date.in_(list(dates)),
        )
    )
    seen: set[tuple[UUID, date]] = set()
    for log, device, schedule in rows.all():
        if log.scheduled_date is None or log.scheduled_for is None or log.slot_number is None:
            continue
        wanted = day_for.get(device.id, unlinked_date)
        if wanted != log.scheduled_date:
            continue
        status = journal_status(log.status, log.delay_minutes)
        if status is None:
            continue
        if log.schedule_id is not None:
            seen.add((log.schedule_id, log.scheduled_date))
        records.append(DoseRecord(log, device, schedule, log.slot_number, log.scheduled_for, status))

    schedules = await session.execute(
        select(Schedule).where(
            Schedule.device_id.in_(list(day_for)),
            Schedule.deleted_at.is_(None),
            Schedule.is_active.is_(True),
        )
    )
    for schedule in schedules.scalars().all():
        device = devices_by_id.get(schedule.device_id)
        if device is None:
            continue
        tz = zone(device.timezone)
        day = day_for[device.id]
        if day < now.astimezone(tz).date() or (schedule.id, day) in seen:
            continue  # past days only show what actually happened
        if not is_scheduled_on(schedule.days_of_week, day):
            continue
        inst = dose_instants(day, schedule.window_start, schedule.window_end, schedule.tolerance_minutes, tz)
        records.append(DoseRecord(None, device, schedule, schedule.slot_number, inst.scheduled_for, JournalStatus.PENDING))
    records.sort(key=lambda r: (r.scheduled_for, r.slot_number))
    return records


def summarize(records: list[DoseRecord]) -> AdherenceSummary:
    summary = AdherenceSummary()
    for r in records:
        if r.log is not None:
            summary.add(r.log.status, r.log.delay_minutes)
        else:
            summary.add(DoseStatus.PENDING.value, None)
    return summary


Indicator = Literal["FULLY_COMPLIANT", "HAS_LATE", "HAS_MISSED", "NO_SCHEDULE"]


def indicator(summary: AdherenceSummary) -> Indicator:
    if summary.scheduled == 0:
        return "NO_SCHEDULE"
    if summary.missed:
        return "HAS_MISSED"
    if summary.taken_late:
        return "HAS_LATE"
    return "FULLY_COMPLIANT"


async def _first_notified(session: AsyncSession, log_ids: list[UUID]) -> dict[UUID, tuple[str, datetime]]:
    if not log_ids:
        return {}
    rows = await session.execute(
        select(Notification.telemetry_log_id, User.full_name, Notification.created_at)
        .join(User, User.id == Notification.user_id)
        .where(Notification.telemetry_log_id.in_(log_ids))
        .order_by(Notification.created_at)
    )
    first: dict[UUID, tuple[str, datetime]] = {}
    for log_id, name, created_at in rows.all():
        if log_id is not None and log_id not in first:
            first[log_id] = (name, created_at)
    return first


async def day_view(session: AsyncSession, user: User, elderly_id: UUID, day: date, now: datetime) -> DayOut:
    await require_role(session, user.id, elderly_id, ALL_ROLES)
    devices = await _elderly_devices(session, elderly_id)
    records = await day_doses(session, elderly_id, devices, {d.id: day for d in devices}, now, unlinked_date=day)
    notified = await _first_notified(session, [r.log.id for r in records if r.log is not None])
    summary = summarize(records)
    cards = []
    for r in records:
        layout = slot_layout(r.slot_number)
        tz = zone(r.device.timezone)
        log = r.log
        who = notified.get(log.id) if log else None
        cards.append(
            DoseCard(
                dose_log_id=log.id if log else None,
                device_id=r.device.id,
                device_nickname=r.device.device_nickname,
                schedule_id=r.schedule.id if r.schedule else None,
                slot_number=r.slot_number,
                meal_relation=layout.meal_relation,
                day_period=layout.day_period,
                medication_name=r.schedule.medication_name if r.schedule else None,
                scheduled_time=r.scheduled_for.astimezone(tz).strftime("%H:%M"),
                status=r.status,
                delay_minutes=log.delay_minutes if log else None,
                actual_open_time=log.actual_open_time if log else None,
                actual_close_time=log.actual_close_time if log else None,
                chime_count=log.chime_count if log else None,
                log_source=log.log_source if log else None,
                notified_caregiver=who[0] if who else None,
                notified_at=who[1] if who else None,
            )
        )
    return DayOut(
        date=day,
        doses_completed=summary.taken,
        doses_total=summary.scheduled,
        adherence_rate=summary.compliance_rate,
        avg_delay_minutes=summary.avg_delay_minutes,
        doses=cards,
    )


async def _rows_between(session: AsyncSession, elderly_id: UUID, start: date, end: date) -> list[TelemetryLog]:
    rows = await session.execute(
        select(TelemetryLog).where(
            TelemetryLog.elderly_id == elderly_id,
            TelemetryLog.status.is_not(None),
            TelemetryLog.scheduled_date >= start,
            TelemetryLog.scheduled_date <= end,
        )
    )
    return list(rows.scalars().all())


def parse_month(month: str) -> tuple[date, date]:
    try:
        year_s, month_s = month.split("-")
        first = date(int(year_s), int(month_s), 1)
    except ValueError:
        raise unprocessable("VALIDATION_ERROR", "month must be YYYY-MM") from None
    last = first.replace(day=pycal.monthrange(first.year, first.month)[1])
    return first, last


async def calendar_view(session: AsyncSession, user: User, elderly_id: UUID, month: str, now: datetime) -> CalendarOut:
    await require_role(session, user.id, elderly_id, ALL_ROLES)
    first, last = parse_month(month)
    # ASSUMPTION: days after "today" (caller's users.timezone) are omitted;
    # the API enum has no "upcoming" indicator.
    today = now.astimezone(zone(user.timezone)).date()
    last_shown = min(last, today)
    by_day: dict[date, AdherenceSummary] = defaultdict(AdherenceSummary)
    total = AdherenceSummary()
    for log in await _rows_between(session, elderly_id, first, last_shown):
        if log.scheduled_date is None:
            continue
        by_day[log.scheduled_date].add(log.status, log.delay_minutes)
        total.add(log.status, log.delay_minutes)
    days = []
    d = first
    while d <= last_shown:
        s = by_day.get(d, AdherenceSummary())
        days.append(
            CalendarDay(
                date=d, indicator=indicator(s), scheduled=s.scheduled, taken_on_time=s.taken_on_time,
                taken_late=s.taken_late, missed=s.missed, pending=s.pending,
            )
        )
        d += timedelta(days=1)
    return CalendarOut(
        month=f"{first.year:04d}-{first.month:02d}",
        compliance_rate=total.compliance_rate,
        avg_delay_minutes=total.avg_delay_minutes,
        days=days,
    )


async def summary_view(session: AsyncSession, user: User, elderly_id: UUID, start: date, end: date) -> SummaryOut:
    await require_role(session, user.id, elderly_id, ALL_ROLES)
    if end < start:
        raise unprocessable("VALIDATION_ERROR", "end must not be before start")
    if (end - start).days > MAX_SUMMARY_DAYS:
        raise unprocessable("VALIDATION_ERROR", f"period is limited to {MAX_SUMMARY_DAYS} days")
    total = AdherenceSummary()
    for log in await _rows_between(session, elderly_id, start, end):
        total.add(log.status, log.delay_minutes)
    return SummaryOut(
        period={"start": start, "end": end},
        total_scheduled=total.scheduled,
        taken_on_time=total.taken_on_time,
        taken_late=total.taken_late,
        missed=total.missed,
        compliance_rate=total.compliance_rate,
        avg_delay_minutes=total.avg_delay_minutes,
    )


async def manual_confirmation(
    session: AsyncSession, user: User, dose_log_id: UUID, body: ManualConfirmationIn, now: datetime
) -> ManualConfirmationOut:
    log = (
        await session.execute(select(TelemetryLog).where(TelemetryLog.id == dose_log_id).with_for_update())
    ).scalar_one_or_none()
    if log is None or log.status is None or log.elderly_id is None:
        raise not_found(message="Dose log not found")
    # CONFLICT with the API List ("Caregiver terkait"): manual confirmation is
    # a write, and the brief makes PEMANTAU read-only, so OWNER/ADMIN only.
    await require_role(session, user.id, log.elderly_id, EDITOR_ROLES)
    if log.status == DoseStatus.TAKEN and log.log_source == LogSource.AUTO_SENSOR:
        raise conflict("ALREADY_TAKEN_BY_DEVICE", "The device already recorded this dose as taken")
    if log.scheduled_for is None or now < log.scheduled_for:
        raise conflict("DOSE_NOT_YET_DUE", "This dose is not due yet")

    device = await session.get(Device, log.device_id)
    tz = zone(device.timezone if device else None)
    confirmed_at = as_aware(body.confirmed_at, tz)
    if body.override_status == "TAKEN_ON_TIME":
        delay = 0
    else:
        schedule = await session.get(Schedule, log.schedule_id) if log.schedule_id else None
        window_end_at = (
            dose_instants(log.scheduled_date, schedule.window_start, schedule.window_end, schedule.tolerance_minutes, tz).window_end_at
            if schedule is not None and log.scheduled_date is not None
            else log.scheduled_for
        )
        delay = max(1, delay_minutes_for(confirmed_at, window_end_at))

    previous = log.status
    log.status = DoseStatus.TAKEN.value
    log.delay_minutes = delay
    log.log_source = LogSource.MANUAL_CAREGIVER_CONFIRMATION.value
    log.event_type = EVENT_MANUAL_CONFIRMATION
    log.confirmed_by_user_id = user.id
    log.confirmation_note = body.note
    log.recorded_at = confirmed_at
    if previous == DoseStatus.MISSED:
        await auto_resolve_missed(session, log.id, now, f"Manually confirmed as taken by {user.full_name}")
    await session.commit()
    logger.info("dose_manually_confirmed", extra={"telemetry_log_id": str(log.id), "user_id": str(user.id)})
    return ManualConfirmationOut(
        dose_log_id=log.id,
        status=body.override_status,
        delay_minutes=delay,
        log_source="MANUAL_CAREGIVER_CONFIRMATION",
        confirmed_by_caregiver_name=user.full_name,
        note=body.note,
    )
