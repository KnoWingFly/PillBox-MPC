"""In-process rules engine (asyncio background task).

Every RULES_ENGINE_INTERVAL_SECONDS:

1. materialize_due_doses: for every active schedule of a paired device, and
   every local date from (today - RULES_ENGINE_LOOKBACK_DAYS) to today in the
   DEVICE's timezone (defaulted from the pairing caregiver's users.timezone),
   create the PENDING dose row once its window_start has passed. The unique
   index on (schedule_id, scheduled_for) makes this idempotent across runs,
   restarts and workers. Doses before the schedule's current timing took effect
   (schedules.effective_from: created, or time/days/tolerance/on-off changed) or
   before the device was paired are never materialized, so a new or edited
   schedule does not back-fill history as "missed".

2. decide_missed: PENDING doses whose deadline_at (window_end + tolerance)
   passed more than MISSED_DECISION_GRACE_SECONDS ago become MISSED, with a
   DOSE_MISSED notification per caregiver (event_key makes it exactly-once).

"Now" in both steps is the DEVICE clock (services/device_clock.py,
FOLLOW_DEVICE_CLOCK): when the emulator's lab clock is moved or sped up, doses
fall due and are missed by the time the pillbox shows, not the server's. A
device clock further than DEVICE_CLOCK_MAX_SKEW_MINUTES from server time is
ignored, doses are materialized up to server time even when the device clock
lags, and the OFFLINE_MAX_WAIT rule below always uses server time.

OFFLINE RULE: a device that was offline may still hold the door events for
the dose in its local buffer. We therefore only decide MISSED when
  (a) the device is ONLINE and has been online for at least
      OFFLINE_FLUSH_WAIT_SECONDS (it reconnects, flushes its buffer, and that
      flush has had time to arrive), or
  (b) the deadline passed more than OFFLINE_MAX_WAIT_MINUTES ago (the device
      looks gone; caregivers must still be told).
If evidence arrives later anyway, telemetry ingestion upgrades MISSED to
TAKEN and auto-resolves the DOSE_MISSED notifications.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, any_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import Device, Elderly, Schedule, TelemetryLog
from app.models.enums import (
    EVENT_RULES_ENGINE_MISSED,
    EVENT_SCHEDULE_DUE,
    Connectivity,
    DoseStatus,
    LogSource,
    NotificationType,
)
from app.services.adherence import dose_instants, is_scheduled_on
from app.services.device_clock import device_now, device_now_sql
from app.services.doses import dose_notification, insert_pending_doses, pending_dose_row
from app.services.leader import RULES_ENGINE_LOCK_KEY, try_lead
from app.services.notifications import load_recipients_many, notify_many
from app.services.timeutil import zone

logger = logging.getLogger(__name__)


def can_decide_missed(device: Device, deadline_at: datetime, now: datetime, settings: Settings) -> bool:
    flushed = (
        device.status == Connectivity.ONLINE
        and device.online_since is not None
        and device.online_since <= now - timedelta(seconds=settings.offline_flush_wait_seconds)
    )
    # Server time on purpose: a device clock that lags (within the followed skew) must not
    # postpone the "caregivers must still be told" rule.
    gave_up_waiting = now >= deadline_at + timedelta(minutes=settings.offline_max_wait_minutes)
    return flushed or gave_up_waiting


async def materialize_due_doses(session: AsyncSession, now: datetime, settings: Settings) -> int:
    rows = await session.execute(
        select(Schedule, Device)
        .join(Device, Device.id == Schedule.device_id)
        .join(Elderly, Elderly.id == Device.elderly_id)
        .where(
            Schedule.deleted_at.is_(None),
            Schedule.is_active.is_(True),
            Elderly.deleted_at.is_(None),
        )
    )
    due: list[dict[str, Any]] = []
    for index, (schedule, device) in enumerate(rows.all()):
        if index and index % settings.rules_engine_yield_every_schedules == 0:
            # Pure Python work for thousands of schedules: let requests run in between.
            await asyncio.sleep(0)
        tz = zone(device.timezone)
        # Never behind server time: doses due by the server clock must exist for the
        # OFFLINE_MAX_WAIT rule even when the device clock lags; a clock ahead (lab demo) is followed.
        clock = max(now, device_now(device, now, settings))
        today = clock.astimezone(tz).date()
        # When the schedule's current timing / the pairing took effect, on the device clock. Not
        # created_at: an edited slot keeps it, and its new time must not back-fill past days.
        not_before = max(schedule.effective_from, device.paired_at or device.created_at) + (clock - now)
        for offset in range(settings.rules_engine_lookback_days, -1, -1):
            day = today - timedelta(days=offset)
            if not is_scheduled_on(schedule.days_of_week, day):
                continue
            inst = dose_instants(day, schedule.window_start, schedule.window_end, schedule.tolerance_minutes, tz)
            if inst.scheduled_for > clock or inst.scheduled_for < not_before:
                continue
            due.append(pending_dose_row(device.id, device.elderly_id, schedule, inst, EVENT_SCHEDULE_DUE))
    # Almost every due dose already exists after the first pass. Compiling multi-row INSERTs
    # for all of them cost seconds of event-loop CPU per pass, so existing keys are read in one
    # indexed query and only new doses are inserted (ON CONFLICT still covers races).
    due = await _not_yet_materialized(session, due)
    created = await insert_pending_doses(session, due)
    await session.commit()
    return created


async def _not_yet_materialized(session: AsyncSession, due: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not due:
        return due
    existing = await session.execute(
        select(TelemetryLog.schedule_id, TelemetryLog.scheduled_for).where(
            # Matches the partial unique index telemetry_logs_dose_key_idx (schedule_id, scheduled_for).
            TelemetryLog.schedule_id == any_(list({row["schedule_id"] for row in due})),
            TelemetryLog.scheduled_for >= min(row["scheduled_for"] for row in due),
            TelemetryLog.scheduled_for.is_not(None),
        )
    )
    keys = {(schedule_id, scheduled_for) for schedule_id, scheduled_for in existing.all()}
    return [row for row in due if (row["schedule_id"], row["scheduled_for"]) not in keys]


async def decide_missed(session: AsyncSession, now: datetime, settings: Settings) -> int:
    """Decides one chunk (RULES_ENGINE_DECIDE_CHUNK_SIZE) of due PENDING doses and commits.
    Returns how many were decided; run_once repeats while chunks come back full."""
    grace = timedelta(seconds=settings.missed_decision_grace_seconds)
    # can_decide_missed() in SQL, so doses of a device still offline (waiting for its flush) are
    # neither locked nor loaded on every pass, and cannot fill a chunk that decides nothing.
    flushed = and_(
        Device.status == Connectivity.ONLINE.value,
        Device.online_since.is_not(None),
        Device.online_since <= now - timedelta(seconds=settings.offline_flush_wait_seconds),
    )
    gave_up_waiting = TelemetryLog.deadline_at <= now - timedelta(minutes=settings.offline_max_wait_minutes)
    rows = await session.execute(
        select(TelemetryLog, Device)
        .join(Device, Device.id == TelemetryLog.device_id)
        .where(
            TelemetryLog.status == DoseStatus.PENDING.value,
            TelemetryLog.deadline_at.is_not(None),
            or_(
                and_(TelemetryLog.deadline_at <= device_now_sql(now, settings) - grace, flushed),
                gave_up_waiting,
            ),
        )
        .order_by(TelemetryLog.deadline_at)
        .limit(settings.rules_engine_decide_chunk_size)
        # Rows being updated by telemetry right now are skipped this round.
        .with_for_update(of=TelemetryLog, skip_locked=True)
    )
    missed = [
        (log, device)
        for log, device in rows.all()
        if log.deadline_at is not None and can_decide_missed(device, log.deadline_at, now, settings)
    ]
    for log, device in missed:
        log.status = DoseStatus.MISSED.value
        log.log_source = LogSource.SYSTEM_RULES_ENGINE.value
        log.event_type = EVENT_RULES_ENGINE_MISSED
        log.delay_minutes = None
        log.recorded_at = device_now(device, now, settings)
    await session.flush()
    # One recipients query and a few multi-row notification INSERTs for the whole pass, instead
    # of a recipients query and an INSERT per dose (a backlog pass decides thousands at once).
    recipients = await load_recipients_many(session, {log.elderly_id for log, _ in missed if log.elderly_id})
    batch = []
    for log, device in missed:
        audience = recipients.get(log.elderly_id, []) if log.elderly_id else []
        spec = dose_notification(log, NotificationType.DOSE_MISSED, zone(device.timezone), audience)
        if spec is not None:
            batch.append((spec, audience, None))
        logger.info("dose_missed", extra={"telemetry_log_id": str(log.id), "device_id": str(device.id)})
    await notify_many(session, batch)
    await session.commit()
    return len(missed)


@dataclass
class RulesPass:
    created: int = 0
    missed: int = 0
    # Materialization failed this pass (decide_missed still ran): reported, so /health does not
    # call a loop "ok" whose doses are never created.
    materialize_failed: bool = False


async def run_once(sessionmaker: async_sessionmaker[AsyncSession], now: datetime, settings: Settings) -> RulesPass:
    created = 0
    materialize_failed = False
    try:
        async with sessionmaker() as session:
            if not await try_lead(session, RULES_ENGINE_LOCK_KEY):
                return RulesPass()  # another backend instance runs this pass
            created = await materialize_due_doses(session, now, settings)
    except Exception:
        # Doses already materialized must still be judged: a failed materialization (e.g. a
        # lock conflict with telemetry) must not also hold back MISSED alerts this pass.
        logger.exception("rules_engine_materialize_failed")
        materialize_failed = True
    missed = 0
    while True:
        # One transaction (and one leader check) per chunk: a backlog after an outage never holds
        # thousands of row locks, and requests get the event loop between chunks.
        async with sessionmaker() as session:
            if not await try_lead(session, RULES_ENGINE_LOCK_KEY):
                return RulesPass(created, missed, materialize_failed)
            decided = await decide_missed(session, now, settings)
        missed += decided
        if decided < settings.rules_engine_decide_chunk_size:
            return RulesPass(created, missed, materialize_failed)
        await asyncio.sleep(0)
