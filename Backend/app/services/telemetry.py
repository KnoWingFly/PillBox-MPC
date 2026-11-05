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

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timing
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
from app.services.app_hub import queue_device_change
from app.services.adherence import DoseInstants, delay_minutes_for, dose_instants, match_dose, on_time_grace
from app.services.device_clock import device_now
from app.services.device_protocol import is_fresh, status_builder
from app.services.doses import forget_dose, get_or_create_dose, notify_dose, report_taken_after_missed, slot_label
from app.services.late_dose import CONFIRM_TAKEN, missed_dose_before_cutoff
from app.services.notifications import (
    NOTE_BY_SENSOR,
    NOTE_DOSE_REPLAYED,
    NotificationSpec,
    cache_recipients,
    note_texts,
    notify,
)
from app.services.presence import device_label, mark_seen
from app.services.timeutil import as_aware, zone

logger = logging.getLogger(__name__)

_KNOWN_TYPES = {t.value for t in DeviceEventType}
_EVENT_ID_MAX_LENGTH = next(
    m.max_length for m in TelemetryEvent.model_fields["event_id"].metadata if getattr(m, "max_length", None)
)
_DOSE_TYPES = {
    DeviceEventType.POPUP_ACTIVATED,
    DeviceEventType.COMPARTMENT_OPENED,
    DeviceEventType.COMPARTMENT_CLOSED,
    DeviceEventType.ALARM_TIMEOUT,
}
_SLOT_REQUIRED = _DOSE_TYPES | {DeviceEventType.UNSCHEDULED_OPEN}
_DOSE_TYPE_VALUES = {t.value for t in _DOSE_TYPES}


@dataclass
class _Prepared:
    index: int
    event: TelemetryEvent
    occurred_at: datetime  # timezone-aware
    reject_reason: str | None


def _validate(
    ev: TelemetryEvent, occurred_at: datetime, now: datetime, earliest: datetime, settings: Settings
) -> str | None:
    """now: latest acceptable device time; earliest: oldest acceptable time for a dose/door event."""
    if ev.event_type not in _KNOWN_TYPES:
        return f"unknown event_type {ev.event_type!r}"
    etype = DeviceEventType(ev.event_type)
    if etype in _SLOT_REQUIRED and ev.slot_number is None:
        return f"slot_number is required for {etype.value}"
    if occurred_at > now + timedelta(minutes=settings.telemetry_max_future_skew_minutes):
        return "occurred_at is too far in the future (check the device clock)"
    if etype in _SLOT_REQUIRED and occurred_at < earliest:
        # Would otherwise create a dose row (or a forced-open alert) for a date the clock invented.
        return "occurred_at is too far in the past (check the device clock)"
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

    started = timing.now_ms()
    # Any authenticated request proves the device is alive. This also locks the
    # device row, so batches from one device are applied one at a time.
    await mark_seen(session, device, now)
    tz = zone(device.timezone)
    # A lab clock moved ahead on purpose is not "too far in the future".
    device_clock = device_now(device, now, settings)
    clock = max(now, device_clock)
    earliest = min(now, device_clock) - timedelta(minutes=settings.telemetry_max_past_skew_minutes)

    results: list[EventResult | None] = [None] * len(req.events)
    events: list[TelemetryEvent | None] = [None] * len(req.events)
    first_index: dict[str, int] = {}
    for i, raw in enumerate(req.events):
        try:
            ev = events[i] = raw if isinstance(raw, TelemetryEvent) else TelemetryEvent.model_validate(raw)
        except ValidationError as exc:
            # Not stored (no valid key to store it under); a resend gets the same answer.
            results[i] = EventResult(event_id=_raw_event_id(raw), status="rejected", reason=_field_errors(exc))
            continue
        if ev.event_id in first_index:
            results[i] = EventResult(event_id=ev.event_id, status="duplicate", reason="repeated within batch")
        else:
            first_index[ev.event_id] = i

    # No up-front "already stored?" query: the claim's ON CONFLICT DO NOTHING
    # detects re-sent events, and only those pay a lookup (one round trip
    # saved on the normal, all-new path).
    prepared = []
    for i in first_index.values():
        ev = events[i]
        assert ev is not None  # only valid events are indexed
        occurred = as_aware(ev.occurred_at, tz)
        prepared.append(_Prepared(i, ev, occurred, _validate(ev, occurred, clock, earliest, settings)))
    prepared.sort(key=lambda p: (p.occurred_at, p.event.event_id))

    # Round trips per batch, not per event: one claim INSERT, one lookup of re-sent events'
    # original outcomes, one load of the device's schedules; recipients are reused per elderly.
    claimed = await _claim_all(session, device, req.batch_id, prepared)
    resent = [p.event.event_id for p in prepared if p.event.event_id not in claimed]
    stored = await _stored_events(session, device, resent)
    schedules = await _ScheduleIndex.load(session, device.id) if any(
        p.reject_reason is None and p.event.event_type in _DOSE_TYPE_VALUES for p in prepared
    ) else _ScheduleIndex([])
    cache_recipients(session)

    log_links: list[dict[str, UUID]] = []  # device_events.id -> telemetry_logs.id
    for item in prepared:
        if timing.enabled():
            timing.log_timing(
                "iot_to_app", "backend_received", correlation_id=item.event.event_id,
                event_type=item.event.event_type, offline_flush=req.is_offline_flush,
                # Device clock vs server clock: meaningful only with a real-time RTC.
                lag_ms=round((now - item.occurred_at).total_seconds() * 1000),
            )
        claimed_id = claimed.get(item.event.event_id)
        if claimed_id is None:
            original = stored.get(item.event.event_id)
            results[item.index] = (
                _duplicate_result(original)
                if original is not None
                else EventResult(event_id=item.event.event_id, status="duplicate")
            )
            continue
        if item.reject_reason is not None:
            results[item.index] = EventResult(
                event_id=item.event.event_id, status="rejected", reason=item.reject_reason
            )
            continue
        token = timing.correlation_id_var.set(item.event.event_id)
        try:
            log_id = await _apply(
                session, device, item.event, item.occurred_at, tz, now, settings, schedules, req.is_offline_flush
            )
        finally:
            timing.correlation_id_var.reset(token)
        if log_id is not None:
            log_links.append({"id": claimed_id, "telemetry_log_id": log_id})
        results[item.index] = EventResult(
            event_id=item.event.event_id,
            status="accepted",
            telemetry_log_id=str(log_id) if log_id else None,
        )

    if log_links:
        # One executemany instead of loading each claim row back (ORM bulk
        # UPDATE by primary key).
        await session.execute(update(DeviceEvent), log_links)
    queue_device_change(session, device.elderly_id, device.id, status=status_builder(device, settings))
    await session.commit()
    timing.log_timing(
        "iot_to_app", "db_committed",
        correlation_id=req.batch_id, event_ids=[p.event.event_id for p in prepared],
        batch_ms=timing.since_ms(started),
    )

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


def _raw_event_id(raw: object) -> str:
    """The event_id of an event that failed validation, so the device can match the answer."""
    value = raw.get("event_id") if isinstance(raw, dict) else None
    return value[:_EVENT_ID_MAX_LENGTH] if isinstance(value, str) else ""


def _field_errors(exc: ValidationError) -> str:
    """Field paths and messages only, never the submitted values."""
    return "invalid fields: " + "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors(include_url=False)
    )


def _duplicate_result(stored: DeviceEvent) -> EventResult:
    return EventResult(
        event_id=stored.event_id,
        status="duplicate",
        telemetry_log_id=str(stored.telemetry_log_id) if stored.telemetry_log_id else None,
        reason=f"original outcome: {stored.outcome}" + (f" ({stored.reject_reason})" if stored.reject_reason else ""),
    )


async def _claim_all(
    session: AsyncSession, device: Device, batch_id: str | None, items: list[_Prepared]
) -> dict[str, UUID]:
    """Inserts the idempotency claims in one executemany (compiled once, rows batched). Returns
    {event_id: claim id} for the events claimed now; a missing event_id was claimed before."""
    if not items:
        return {}
    rows = [
        {
            "device_id": device.id,
            "event_id": item.event.event_id,
            "batch_id": batch_id,
            "event_type": item.event.event_type,
            "slot_number": item.event.slot_number,
            "schedule_ref": item.event.schedule_id,
            "occurred_at": item.occurred_at,
            "chime_count": item.event.chime_count,
            "payload": item.event.model_dump(mode="json"),
            "outcome": "REJECTED" if item.reject_reason else "ACCEPTED",
            "reject_reason": item.reject_reason,
        }
        for item in items
    ]
    table = DeviceEvent.__table__
    stmt = (
        insert(table)
        .on_conflict_do_nothing(index_elements=[table.c.device_id, table.c.event_id])
        .returning(table.c.event_id, table.c.id)
    )
    return {event_id: claim_id for event_id, claim_id in (await session.execute(stmt, rows)).all()}


async def _stored_events(session: AsyncSession, device: Device, event_ids: list[str]) -> dict[str, DeviceEvent]:
    """The stored claims of re-sent events, for their original outcome."""
    if not event_ids:
        return {}
    rows = await session.execute(
        select(DeviceEvent).where(DeviceEvent.device_id == device.id, DeviceEvent.event_id.in_(event_ids))
    )
    return {stored.event_id: stored for stored in rows.scalars().all()}


async def _apply(
    session: AsyncSession,
    device: Device,
    ev: TelemetryEvent,
    occurred_at: datetime,
    tz: ZoneInfo,
    now: datetime,
    settings: Settings,
    schedules: "_ScheduleIndex",
    offline_flush: bool = False,
) -> UUID | None:
    etype = DeviceEventType(ev.event_type)
    if etype in _DOSE_TYPES:
        return await _apply_dose_event(
            session, device, ev, etype, occurred_at, tz, now, settings, schedules, offline_flush
        )
    if etype is DeviceEventType.UNSCHEDULED_OPEN:
        return await _apply_unscheduled_open(session, device, ev, occurred_at, tz, settings)
    if etype is DeviceEventType.BATTERY_STATUS and ev.battery_percent is not None:
        # Old buffered readings must not overwrite a fresher heartbeat value.
        if is_fresh(occurred_at, now, settings):
            device.battery_percentage = ev.battery_percent
    # REFILL_MAINTENANCE, ALARM_STARTED/STOPPED, NETWORK_RECOVERED: kept in
    # device_events as an audit trail; stock arrives via heartbeat stock_count.
    return None


class _ScheduleIndex:
    """The device's live schedules, loaded once per telemetry batch."""

    def __init__(self, schedules: list[Schedule]) -> None:
        self._by_id = {s.id: s for s in schedules}
        self._active_by_slot = {s.slot_number: s for s in schedules if s.is_active}

    @classmethod
    async def load(cls, session: AsyncSession, device_id: UUID) -> "_ScheduleIndex":
        rows = await session.execute(
            select(Schedule).where(Schedule.device_id == device_id, Schedule.deleted_at.is_(None))
        )
        return cls(list(rows.scalars().all()))

    def resolve(self, slot_number: int | None, schedule_ref: str | None) -> Schedule | None:
        """By schedule_id when it names an active schedule of this device, else by slot."""
        if schedule_ref:
            try:
                by_id = self._by_id.get(UUID(schedule_ref))
            except ValueError:
                by_id = None
            if by_id is not None and by_id.is_active:
                return by_id
        return self._active_by_slot.get(slot_number) if slot_number is not None else None


async def _apply_dose_event(
    session: AsyncSession,
    device: Device,
    ev: TelemetryEvent,
    etype: DeviceEventType,
    occurred_at: datetime,
    tz: ZoneInfo,
    now: datetime,
    settings: Settings,
    schedules: _ScheduleIndex,
    offline_flush: bool = False,
) -> UUID | None:
    schedule = schedules.resolve(ev.slot_number, ev.schedule_id)
    if schedule is None:
        logger.info("dose_event_without_schedule", extra={"device_id": str(device.id), "slot": ev.slot_number})
        return None
    # A device timeout may arrive up to one tolerance late (chamber queued behind
    # another, see adherence.match_dose); it only ever turns a PENDING dose MISSED.
    late_grace = (
        timedelta(minutes=schedule.tolerance_minutes, seconds=settings.missed_decision_grace_seconds)
        if etype is DeviceEventType.ALARM_TIMEOUT
        else timedelta(0)
    )
    inst = match_dose(
        occurred_at,
        schedule.window_start,
        schedule.window_end,
        schedule.tolerance_minutes,
        schedule.days_of_week,
        tz,
        settings.dose_early_accept_minutes,
        late_grace,
    )
    log: TelemetryLog | None = None
    if inst is None and etype in (DeviceEventType.COMPARTMENT_OPENED, DeviceEventType.COMPARTMENT_CLOSED):
        # After its deadline, but a caregiver re-opened this missed dose ("Buka bilik sekarang").
        log = await _released_dose(session, schedule, occurred_at)
        if log is not None and log.scheduled_date is not None:
            inst = dose_instants(log.scheduled_date, schedule.window_start, schedule.window_end, schedule.tolerance_minutes, tz)
    if inst is None:
        logger.info(
            "dose_event_outside_window",
            extra={"device_id": str(device.id), "slot": ev.slot_number, "event_type": etype.value},
        )
        return None

    if log is None:
        log = await get_or_create_dose(session, device.id, device.elderly_id, schedule, inst, etype.value)
        if etype is DeviceEventType.POPUP_ACTIVATED and _is_replay(log, occurred_at, offline_flush):
            await forget_dose(session, log, now, note_texts(NOTE_DOSE_REPLAYED))
            logger.info("dose_replayed", extra={"device_id": str(device.id), "slot": ev.slot_number})
            log = await get_or_create_dose(session, device.id, device.elderly_id, schedule, inst, etype.value)
    grace = on_time_grace(schedule.tolerance_minutes, settings.on_time_grace_minutes)

    if etype is DeviceEventType.COMPARTMENT_OPENED:
        await _mark_taken(
            session, log, inst, occurred_at, via_open=True, chime_count=ev.chime_count, tz=tz, now=now, grace_minutes=grace
        )
    elif etype is DeviceEventType.COMPARTMENT_CLOSED:
        if log.status == DoseStatus.TAKEN:
            if log.actual_close_time is None and (log.actual_open_time is None or occurred_at >= log.actual_open_time):
                log.actual_close_time = occurred_at
        else:
            await _mark_taken(
                session, log, inst, occurred_at, via_open=False, chime_count=ev.chime_count, tz=tz, now=now, grace_minutes=grace
            )
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


def _is_replay(log: TelemetryLog, popup_at: datetime, offline_flush: bool) -> bool:
    """The chamber popped up for a dose whose outcome was recorded at a LATER device time: the
    pillbox clock was set back (emulator lab clock: "Sync Jam Nyata", then "Jadwal Berikutnya"),
    and on the pillbox this dose has not happened yet. Without this the new take would land on
    the old row, which is already TAKEN, and no notification would be sent.

    Not for an offline flush: there an earlier pop-up arriving after a rules-engine MISSED is
    late evidence, handled by the MISSED -> TAKEN upgrade. A caregiver's confirmation is kept."""
    if log.status not in (DoseStatus.TAKEN, DoseStatus.MISSED) or log.recorded_at is None:
        return False
    if log.log_source == LogSource.MANUAL_CAREGIVER_CONFIRMATION:
        return False
    if log.log_source == LogSource.SYSTEM_RULES_ENGINE and offline_flush:
        return False
    return log.recorded_at > popup_at


async def _released_dose(session: AsyncSession, schedule: Schedule, occurred_at: datetime) -> TelemetryLog | None:
    """The MISSED dose of this schedule whose late release covers occurred_at (services/late_dose.py)."""
    return (
        await session.execute(
            select(TelemetryLog)
            .where(
                TelemetryLog.schedule_id == schedule.id,
                TelemetryLog.status == DoseStatus.MISSED.value,
                TelemetryLog.late_release_until >= occurred_at,
                TelemetryLog.scheduled_for <= occurred_at,
            )
            .order_by(TelemetryLog.scheduled_for.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()


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
    grace_minutes: int,
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
            log.delay_minutes = delay_minutes_for(taken_at, inst.window_end_at, grace_minutes)
        return

    previous = log.status
    log.status = DoseStatus.TAKEN.value
    log.delay_minutes = delay_minutes_for(taken_at, inst.window_end_at, grace_minutes)
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
        await report_taken_after_missed(session, log, tz, now, note_texts(NOTE_BY_SENSOR))
        return
    ntype = NotificationType.DOSE_LATE if (log.delay_minutes or 0) > 0 else NotificationType.DOSE_TAKEN
    await notify_dose(session, log, ntype, tz)


async def _apply_unscheduled_open(
    session: AsyncSession, device: Device, ev: TelemetryEvent, occurred_at: datetime, tz: ZoneInfo, settings: Settings
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
        missed = await missed_dose_before_cutoff(session, device, ev.slot_number, occurred_at, tz, settings)
        if missed is not None:
            # Forced open soon after this slot's dose was missed: probably taken late. Linked to
            # the missed dose so the caregiver can confirm it (and it resolves with it).
            await notify(
                session,
                NotificationSpec(
                    type=NotificationType.UNSCHEDULED_OPEN,
                    severity=Severity.WARNING,
                    event_key=f"UNSCHEDULED_OPEN:{log.id}",
                    elderly_id=device.elderly_id,
                    device_id=device.id,
                    telemetry_log_id=missed.id,
                    params={
                        "slot": slot_label(ev.slot_number),
                        "device": device_label(device),
                        "time": occurred_at.astimezone(tz).strftime("%H:%M"),
                        "scheduled": missed.scheduled_for.astimezone(tz).strftime("%H:%M") if missed.scheduled_for else "-",
                    },
                    slot_number=ev.slot_number,
                    variant="AFTER_MISSED",
                    actions=[CONFIRM_TAKEN],
                ),
            )
            return log.id
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
                slot_number=ev.slot_number,
            ),
        )
    return log.id
