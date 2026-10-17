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
fall due and are missed by the time the pillbox shows, not the server's.

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
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
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
from app.services.doses import notify_dose, pending_dose_row, pending_doses_insert_stmt
from app.services.timeutil import zone

logger = logging.getLogger(__name__)

# 10 columns per row; keeps each statement far below Postgres' 32767 bind-parameter limit.
_INSERT_CHUNK_ROWS = 1000


def can_decide_missed(device: Device, deadline_at: datetime, now: datetime, settings: Settings) -> bool:
    flushed = (
        device.status == Connectivity.ONLINE
        and device.online_since is not None
        and device.online_since <= now - timedelta(seconds=settings.offline_flush_wait_seconds)
    )
    gave_up_waiting = device_now(device, now, settings) >= deadline_at + timedelta(
        minutes=settings.offline_max_wait_minutes
    )
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
    for schedule, device in rows.all():
        tz = zone(device.timezone)
        clock = device_now(device, now, settings)
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
    # A few multi-row statements instead of one round trip per (schedule, day):
    # every pass re-offers all due doses and ON CONFLICT skips existing ones.
    created = 0
    for start in range(0, len(due), _INSERT_CHUNK_ROWS):
        result = await session.execute(pending_doses_insert_stmt(due[start:start + _INSERT_CHUNK_ROWS]))
        created += len(result.scalars().all())
    await session.commit()
    return created


async def decide_missed(session: AsyncSession, now: datetime, settings: Settings) -> int:
    grace = timedelta(seconds=settings.missed_decision_grace_seconds)
    rows = await session.execute(
        select(TelemetryLog, Device)
        .join(Device, Device.id == TelemetryLog.device_id)
        .where(
            TelemetryLog.status == DoseStatus.PENDING.value,
            TelemetryLog.deadline_at.is_not(None),
            TelemetryLog.deadline_at <= device_now_sql(now, settings) - grace,
        )
        .order_by(TelemetryLog.deadline_at)
        # Rows being updated by telemetry right now are skipped this round.
        .with_for_update(of=TelemetryLog, skip_locked=True)
    )
    decided = 0
    for log, device in rows.all():
        if log.deadline_at is None or not can_decide_missed(device, log.deadline_at, now, settings):
            continue
        log.status = DoseStatus.MISSED.value
        log.log_source = LogSource.SYSTEM_RULES_ENGINE.value
        log.event_type = EVENT_RULES_ENGINE_MISSED
        log.delay_minutes = None
        log.recorded_at = device_now(device, now, settings)
        await session.flush()
        await notify_dose(session, log, NotificationType.DOSE_MISSED, zone(device.timezone))
        decided += 1
        logger.info("dose_missed", extra={"telemetry_log_id": str(log.id), "device_id": str(device.id)})
    await session.commit()
    return decided


async def run_once(sessionmaker: async_sessionmaker[AsyncSession], now: datetime, settings: Settings) -> tuple[int, int]:
    async with sessionmaker() as session:
        created = await materialize_due_doses(session, now, settings)
    async with sessionmaker() as session:
        missed = await decide_missed(session, now, settings)
    return created, missed


async def rules_engine_loop(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    logger.info("rules_engine_started", extra={"interval_s": settings.rules_engine_interval_seconds})
    while True:
        try:
            created, missed = await run_once(sessionmaker, datetime.now(UTC), settings)
            if created or missed:
                logger.info("rules_engine_pass", extra={"pending_created": created, "missed": missed})
        except Exception:
            # Keep the loop alive (DB blips); the next pass retries idempotently.
            logger.exception("rules_engine_pass_failed")
        await asyncio.sleep(settings.rules_engine_interval_seconds)
