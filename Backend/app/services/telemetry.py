"""Device telemetry ingestion.

Idempotency: each event is first claimed in device_events with
INSERT ... ON CONFLICT (device_id, event_id) DO NOTHING. A re-sent event_id
does nothing and returns the outcome stored the first time. The batch is one
transaction: if anything unexpected fails, nothing is committed (including
the claims) and the device retries the whole batch later.

Ordering: events are applied in device-timestamp order (occurred_at, then
event_id), not arrival order, so an offline buffer flushed after Wi-Fi
returns is processed exactly as it happened. Naive timestamps are read in the
device's timezone (the emulator sends naive local time).

Dose semantics (see services/adherence.py for the time rules):
- COMPARTMENT_OPENED in a dose window  -> TAKEN at the open time. The emulator
  defines "lid opened = pill taken" (scheduler.open_compartment).
- COMPARTMENT_CLOSED in a dose window  -> records actual_close_time; if no open
  was seen for that dose (a device that only reports closing), the close
  marks it TAKEN.
- ALARM_TIMEOUT                         -> device-side MISSED for a PENDING dose.
- POPUP_ACTIVATED                       -> ensures the PENDING dose row exists.
- UNSCHEDULED_OPEN                      -> non-dose log row + critical alert.
Sensor evidence of taking can upgrade a MISSED dose (decided while the device
was offline) to TAKEN; it never overrides a caregiver's manual confirmation.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models import Device, DeviceEvent, Schedule, TelemetryLog
from app.models.enums import (
    DeviceEventType,
    DoseStatus,
    LogSource,
    NotificationType,
    Severity,
)
from app.schemas.device_protocol import (
    EventResult,
    RejectedEvent,
    TelemetryEvent,
    TelemetryRequest,
    TelemetryResponse,
)
from app.services.adherence import DoseInstants, delay_minutes_for, match_dose
from app.services.device_protocol import is_fresh
from app.services.doses import auto_resolve_missed, get_or_create_dose, notify_dose, slot_label
from app.services.notifications import NotificationSpec, notify
from app.services.presence import device_label, mark_seen
from app.services.timeutil import as_aware, zone

logger = logging.getLogger(__name__)

_KNOWN_TYPES = {t.value for t in DeviceEventType}
_DOSE_TYPES = {
    DeviceEventType.POPUP_ACTIVATED,
    DeviceEventType.COMPARTMENT_OPENED,
    DeviceEventType.COMPARTMENT_CLOSED,
    DeviceEventType.ALARM_TIMEOUT,
}
_SLOT_REQUIRED = _DOSE_TYPES | {DeviceEventType.UNSCHEDULED_OPEN}


@dataclass
class _Prepared:
    index: int
    event: TelemetryEvent
    occurred_at: datetime  # timezone-aware
    reject_reason: str | None


def _validate(ev: TelemetryEvent, occurred_at: datetime, now: datetime, settings: Settings) -> str | None:
    if ev.event_type not in _KNOWN_TYPES:
        return f"unknown event_type {ev.event_type!r}"
    etype = DeviceEventType(ev.event_type)
    if etype in _SLOT_REQUIRED and ev.slot_number is None:
        return f"slot_number is required for {etype.value}"
    if occurred_at > now + timedelta(minutes=settings.telemetry_max_future_skew_minutes):
        return "occurred_at is too far in the future (check the device clock)"
    return None


async def ingest_batch(
    session: AsyncSession, device: Device, req: TelemetryRequest, now: datetime, settings: Settings
) -> TelemetryResponse:
    if len(req.events) > settings.telemetry_max_batch_size:
        raise AppError(
            413,
            "BATCH_TOO_LARGE",
            f"At most {settings.telemetry_max_batch_size} events per batch",
            details={"max_batch_size": settings.telemetry_max_batch_size},
        )

    # Any authenticated request proves the device is alive. This also locks the
    # device row, so batches from one device are applied one at a time.
    await mark_seen(session, device, now)
    tz = zone(device.timezone)

    results: list[EventResult | None] = [None] * len(req.events)
    first_index: dict[str, int] = {}
    for i, ev in enumerate(req.events):
        if ev.event_id in first_index:
            results[i] = EventResult(event_id=ev.event_id, status="duplicate", reason="repeated within batch")
        else:
            first_index[ev.event_id] = i

    existing = await session.execute(
        select(DeviceEvent).where(
            DeviceEvent.device_id == device.id, DeviceEvent.event_id.in_(list(first_index))
        )
    )
    for stored in existing.scalars().all():
        results[first_index.pop(stored.event_id)] = _duplicate_result(stored)

    prepared = []
    for i in first_index.values():
        ev = req.events[i]
        occurred = as_aware(ev.occurred_at, tz)
        prepared.append(_Prepared(i, ev, occurred, _validate(ev, occurred, now, settings)))
    prepared.sort(key=lambda p: (p.occurred_at, p.event.event_id))

    for item in prepared:
        claimed = await _claim(session, device, req.batch_id, item)
        if not claimed:
            # Same event_id committed concurrently by another request.
            results[item.index] = EventResult(event_id=item.event.event_id, status="duplicate")
            continue
        if item.reject_reason is not None:
            results[item.index] = EventResult(
                event_id=item.event.event_id, status="rejected", reason=item.reject_reason
            )
            continue
        log_id = await _apply(session, device, item.event, item.occurred_at, tz, now, settings)
        if log_id is not None:
            claimed.telemetry_log_id = log_id
        results[item.index] = EventResult(
            event_id=item.event.event_id,
            status="accepted",
            telemetry_log_id=str(log_id) if log_id else None,
        )

    await session.commit()

    final = [r for r in results if r is not None]
    accepted = sum(1 for r in final if r.status == "accepted")
    duplicates = sum(1 for r in final if r.status == "duplicate")
    rejected = [RejectedEvent(event_id=r.event_id, reason=r.reason or "") for r in final if r.status == "rejected"]
    logger.info(
        "telemetry_batch",
        extra={
            "device_id": str(device.id), "batch_id": req.batch_id, "offline_flush": req.is_offline_flush,
            "accepted": accepted, "duplicates": duplicates, "rejected": len(rejected),
        },
    )
    return TelemetryResponse(
        server_time=now,
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
        latest_config_version=device.config_version,
        results=final,
    )


def _duplicate_result(stored: DeviceEvent) -> EventResult:
    return EventResult(
        event_id=stored.event_id,
        status="duplicate",
        telemetry_log_id=str(stored.telemetry_log_id) if stored.telemetry_log_id else None,
        reason=f"original outcome: {stored.outcome}" + (f" ({stored.reject_reason})" if stored.reject_reason else ""),
    )


async def _claim(
    session: AsyncSession, device: Device, batch_id: str | None, item: _Prepared
) -> DeviceEvent | None:
    ev = item.event
    stmt = (
        insert(DeviceEvent)
        .values(
            device_id=device.id,
            event_id=ev.event_id,
            batch_id=batch_id,
            event_type=ev.event_type,
            slot_number=ev.slot_number,
            schedule_ref=ev.schedule_id,
            occurred_at=item.occurred_at,
            chime_count=ev.chime_count,
            payload=ev.model_dump(mode="json"),
            outcome="REJECTED" if item.reject_reason else "ACCEPTED",
            reject_reason=item.reject_reason,
        )
        .on_conflict_do_nothing(index_elements=[DeviceEvent.device_id, DeviceEvent.event_id])
        .returning(DeviceEvent.id)
    )
    new_id = (await session.execute(stmt)).scalar_one_or_none()
    if new_id is None:
        return None
    return await session.get(DeviceEvent, new_id)


async def _apply(
    session: AsyncSession,
    device: Device,
    ev: TelemetryEvent,
    occurred_at: datetime,
    tz: ZoneInfo,
    now: datetime,
    settings: Settings,
) -> UUID | None:
    etype = DeviceEventType(ev.event_type)
    if etype in _DOSE_TYPES:
        return await _apply_dose_event(session, device, ev, etype, occurred_at, tz, now, settings)
    if etype is DeviceEventType.UNSCHEDULED_OPEN:
        return await _apply_unscheduled_open(session, device, ev, occurred_at, tz)
    if etype is DeviceEventType.BATTERY_STATUS and ev.battery_percent is not None:
        # Old buffered readings must not overwrite a fresher heartbeat value.
        if is_fresh(occurred_at, now, settings):
            device.battery_percentage = ev.battery_percent
    # REFILL_MAINTENANCE, ALARM_STARTED/STOPPED, NETWORK_RECOVERED: kept in
    # device_events as an audit trail; stock arrives via heartbeat stock_count.
    return None


async def resolve_schedule(
    session: AsyncSession, device_id: UUID, slot_number: int | None, schedule_ref: str | None
) -> Schedule | None:
    if schedule_ref:
        try:
            ref = UUID(schedule_ref)
        except ValueError:
            ref = None
        if ref is not None:
            by_id = await session.execute(
                select(Schedule).where(
                    Schedule.id == ref, Schedule.device_id == device_id, Schedule.deleted_at.is_(None)
                )
            )
            schedule = by_id.scalar_one_or_none()
            if schedule is not None and schedule.is_active:
                return schedule
    if slot_number is None:
        return None
    by_slot = await session.execute(
        select(Schedule).where(
            Schedule.device_id == device_id,
            Schedule.slot_number == slot_number,
            Schedule.deleted_at.is_(None),
            Schedule.is_active.is_(True),
        )
    )
    return by_slot.scalar_one_or_none()


async def _apply_dose_event(
    session: AsyncSession,
    device: Device,
    ev: TelemetryEvent,
    etype: DeviceEventType,
    occurred_at: datetime,
    tz: ZoneInfo,
    now: datetime,
    settings: Settings,
) -> UUID | None:
    schedule = await resolve_schedule(session, device.id, ev.slot_number, ev.schedule_id)
    if schedule is None:
        logger.info("dose_event_without_schedule", extra={"device_id": str(device.id), "slot": ev.slot_number})
        return None
    inst = match_dose(
        occurred_at,
        schedule.window_start,
        schedule.window_end,
        schedule.tolerance_minutes,
        schedule.days_of_week,
        tz,
        settings.dose_early_accept_minutes,
    )
    if inst is None:
        logger.info(
            "dose_event_outside_window",
            extra={"device_id": str(device.id), "slot": ev.slot_number, "event_type": etype.value},
        )
        return None

    log = await get_or_create_dose(session, device.id, device.elderly_id, schedule, inst, etype.value)

    if etype is DeviceEventType.COMPARTMENT_OPENED:
        await _mark_taken(session, log, inst, occurred_at, via_open=True, chime_count=ev.chime_count, tz=tz, now=now)
    elif etype is DeviceEventType.COMPARTMENT_CLOSED:
        if log.status == DoseStatus.TAKEN:
            if log.actual_close_time is None and (log.actual_open_time is None or occurred_at >= log.actual_open_time):
                log.actual_close_time = occurred_at
        else:
            await _mark_taken(session, log, inst, occurred_at, via_open=False, chime_count=ev.chime_count, tz=tz, now=now)
    elif etype is DeviceEventType.ALARM_TIMEOUT:
        if log.status == DoseStatus.PENDING:
            log.status = DoseStatus.MISSED.value
            log.log_source = LogSource.AUTO_SENSOR.value
            log.event_type = etype.value
            log.chime_count = ev.chime_count
            log.recorded_at = occurred_at
            await session.flush()
            await notify_dose(session, log, NotificationType.DOSE_MISSED, tz)
    elif etype is DeviceEventType.POPUP_ACTIVATED and log.chime_count is None and ev.chime_count is not None:
        log.chime_count = ev.chime_count
    return log.id


async def _mark_taken(
    session: AsyncSession,
    log: TelemetryLog,
    inst: DoseInstants,
    taken_at: datetime,
    *,
    via_open: bool,
    chime_count: int | None,
    tz: ZoneInfo,
    now: datetime,
) -> None:
    if log.log_source == LogSource.MANUAL_CAREGIVER_CONFIRMATION:
        # A caregiver already confirmed this dose; keep their decision and only
        # attach the sensor timestamp.
        if via_open and log.actual_open_time is None:
            log.actual_open_time = taken_at
        return

    if log.status == DoseStatus.TAKEN:
        # Already taken (e.g. by a close event); an earlier open refines it.
        if via_open and (log.actual_open_time is None or taken_at < log.actual_open_time):
            log.actual_open_time = taken_at
            log.delay_minutes = delay_minutes_for(taken_at, inst.window_end_at)
        return

    previous = log.status
    log.status = DoseStatus.TAKEN.value
    log.delay_minutes = delay_minutes_for(taken_at, inst.window_end_at)
    log.log_source = LogSource.AUTO_SENSOR.value
    log.event_type = DeviceEventType.COMPARTMENT_OPENED.value if via_open else DeviceEventType.COMPARTMENT_CLOSED.value
    log.recorded_at = taken_at
    if via_open:
        log.actual_open_time = taken_at
    else:
        log.actual_close_time = taken_at
    if chime_count is not None:
        log.chime_count = chime_count
    await session.flush()

    if previous == DoseStatus.MISSED:
        await auto_resolve_missed(
            session, log.id, now, f"Device reported the dose taken at {taken_at.astimezone(tz).isoformat()}"
        )
    ntype = NotificationType.DOSE_LATE if (log.delay_minutes or 0) > 0 else NotificationType.DOSE_TAKEN
    await notify_dose(session, log, ntype, tz)


async def _apply_unscheduled_open(
    session: AsyncSession, device: Device, ev: TelemetryEvent, occurred_at: datetime, tz: ZoneInfo
) -> UUID:
    log = TelemetryLog(
        device_id=device.id,
        elderly_id=device.elderly_id,
        slot_number=ev.slot_number,
        event_type=DeviceEventType.UNSCHEDULED_OPEN.value,
        status=None,
        actual_open_time=occurred_at,
        log_source=LogSource.AUTO_SENSOR.value,
        recorded_at=occurred_at,
    )
    session.add(log)
    await session.flush()
    if device.elderly_id is not None and ev.slot_number is not None:
        await notify(
            session,
            NotificationSpec(
                type=NotificationType.UNSCHEDULED_OPEN,
                severity=Severity.CRITICAL,
                event_key=f"UNSCHEDULED_OPEN:{log.id}",
                elderly_id=device.elderly_id,
                device_id=device.id,
                telemetry_log_id=log.id,
                params={
                    "slot": slot_label(ev.slot_number),
                    "device": device_label(device),
                    "time": occurred_at.astimezone(tz).strftime("%H:%M"),
                },
            ),
        )
    return log.id
