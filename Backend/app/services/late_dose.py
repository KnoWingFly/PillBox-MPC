"""A MISSED dose that is still taken late.

After a dose window closes the pillbox locks the chamber. From the DOSE_MISSED
notification a caregiver can then:

- "Buka bilik sekarang" (release, device PIN): the backend sends `release_slot`
  and the pillbox pops the chamber up again for LATE_RELEASE_MINUTES. Opening it
  in that time is recorded as TAKEN (late) through the normal telemetry path
  (telemetry_logs.late_release_until widens the dose's acceptance window).
- "Sudah diminum" (confirm): manual confirmation as TAKEN_LATE.

Either way the missed alert is resolved (kept in history with a note) and every
caregiver gets a "akhirnya diminum" DOSE_LATE notification (doses.report_taken_after_missed).

Safety cutoff: both are allowed only until LATE_RELEASE_CUTOFF_FRACTION of the way
from the dose's schedule time to the device's next dose (any slot), so a late dose
never comes too close to the next one (double dose). After the cutoff the app tells
the caregiver to wait for the next schedule.

A forced open soon after a miss (UNSCHEDULED_OPEN before the cutoff, same slot) is
reported as "mungkin diminum terlambat" linked to the missed dose, with the confirm
action, instead of only an alarm (see telemetry._apply_unscheduled_open).
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import conflict, not_found
from app.models import Device, Notification, Schedule, TelemetryLog, User
from app.models.enums import EDITOR_ROLES, DoseStatus, NotificationType
from app.schemas.journal import ManualConfirmationIn, ManualConfirmationOut
from app.schemas.notifications import LateReleaseOut
from app.services.access import get_device_for_user
from app.services.adherence import dose_instants, is_scheduled_on
from app.services.connection_manager import DeviceCommand
from app.services.device_clock import device_now
from app.services.timeutil import zone

logger = logging.getLogger(__name__)

# Feed actions (NotificationItem.actions).
LATE_RELEASE = "LATE_RELEASE"
CONFIRM_TAKEN = "CONFIRM_TAKEN"


async def release_cutoff(
    session: AsyncSession, device_id: UUID, log: TelemetryLog, tz: ZoneInfo, settings: Settings
) -> datetime:
    """Latest moment a missed dose may still be taken."""
    assert log.scheduled_for is not None and log.scheduled_date is not None
    schedules = (
        await session.execute(
            select(Schedule).where(
                Schedule.device_id == device_id, Schedule.deleted_at.is_(None), Schedule.is_active.is_(True)
            )
        )
    ).scalars().all()
    upcoming = []
    for schedule in schedules:
        for offset in range(3):
            day = log.scheduled_date + timedelta(days=offset)
            if not is_scheduled_on(schedule.days_of_week, day):
                continue
            inst = dose_instants(day, schedule.window_start, schedule.window_end, schedule.tolerance_minutes, tz)
            if inst.scheduled_for > log.scheduled_for:
                upcoming.append(inst.scheduled_for)
    next_dose = min(upcoming, default=log.scheduled_for + timedelta(days=1))
    return log.scheduled_for + (next_dose - log.scheduled_for) * settings.late_release_cutoff_fraction


def _too_late(cutoff: datetime, tz: ZoneInfo) -> Exception:
    return conflict(
        "LATE_DOSE_TOO_LATE",
        f"Sudah lewat batas aman (pukul {cutoff.astimezone(tz):%H:%M}): terlalu dekat dengan jadwal berikutnya. "
        "Jangan diminum, tunggu jadwal berikutnya.",
        details={"cutoff_at": cutoff.isoformat()},
    )


async def _missed_dose(
    session: AsyncSession, user: User, notification_id: UUID
) -> tuple[Notification, TelemetryLog, Device]:
    """The missed dose behind one of the caregiver's notifications, locked; OWNER/ADMIN only."""
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise not_found(message="Notification not found")
    log = (
        await session.execute(select(TelemetryLog).where(TelemetryLog.id == n.telemetry_log_id).with_for_update())
    ).scalar_one_or_none() if n.telemetry_log_id else None
    if log is None or log.scheduled_for is None or log.slot_number is None:
        raise conflict("NOT_A_DOSE_NOTIFICATION", "This notification is not about a scheduled dose")
    if log.status != DoseStatus.MISSED:
        raise conflict("DOSE_NOT_MISSED", "Dosis ini sudah tercatat diminum.")
    device, _ = await get_device_for_user(session, user.id, log.device_id, EDITOR_ROLES)
    return n, log, device


async def release(
    session: AsyncSession, user: User, notification_id: UUID, pin: str, settings: Settings, now: datetime
) -> LateReleaseOut:
    # Imported here: device_management imports the notification feed chain at module level.
    from app.services.device_management import _check_pin, send_command_or_raise

    n, log, device = await _missed_dose(session, user, notification_id)
    if n.type != NotificationType.DOSE_MISSED:
        raise conflict("NOT_A_MISSED_NOTIFICATION", "Only a missed-dose notification can re-open the compartment")
    await _check_pin(user.id, device, pin, settings, "DEVICE_PIN_INCORRECT")
    tz = zone(device.timezone)
    clock = device_now(device, now, settings)
    cutoff = await release_cutoff(session, device.id, log, tz, settings)
    if clock >= cutoff:
        raise _too_late(cutoff, tz)
    until = min(clock + timedelta(minutes=settings.late_release_minutes), cutoff)
    # Stored before the command: the device may report the lid open right after its ack.
    log.late_release_until = until
    log_id, slot, scheduled_for = log.id, log.slot_number, log.scheduled_for
    await session.commit()  # do not hold a transaction while waiting for the ack

    try:
        ack = await send_command_or_raise(
            device,
            DeviceCommand.RELEASE_SLOT,
            {
                "slot_number": slot,
                # Naive local time, like every time the device keeps (its RTC has no zone).
                "until": until.astimezone(tz).replace(tzinfo=None).isoformat(timespec="seconds"),
                "scheduled_for": scheduled_for.astimezone(tz).replace(tzinfo=None).isoformat(timespec="seconds"),
            },
            settings,
        )
    except Exception:
        row = await session.get(TelemetryLog, log_id, with_for_update=True)
        if row is not None and row.late_release_until == until:
            row.late_release_until = None
            await session.commit()
        raise
    logger.info("late_release", extra={"telemetry_log_id": str(log_id), "slot": slot, "user_id": str(user.id)})
    return LateReleaseOut(
        notification_id=n.id,
        dose_log_id=log_id,
        slot_number=slot,
        release_until=until.astimezone(tz),
        cutoff_at=cutoff.astimezone(tz),
        command_id=ack.command_id,
    )


async def confirm_taken(
    session: AsyncSession, user: User, notification_id: UUID, note: str | None, settings: Settings, now: datetime
) -> ManualConfirmationOut:
    from app.services import journal

    _, log, device = await _missed_dose(session, user, notification_id)
    tz = zone(device.timezone)
    clock = device_now(device, now, settings)
    cutoff = await release_cutoff(session, device.id, log, tz, settings)
    if clock >= cutoff:
        raise _too_late(cutoff, tz)
    body = ManualConfirmationIn(
        override_status="TAKEN_LATE", confirmed_at=clock, note=note or "Dikonfirmasi dari notifikasi"
    )
    return await journal.manual_confirmation(session, user, log.id, body, now, settings)


async def missed_dose_before_cutoff(
    session: AsyncSession, device: Device, slot_number: int, at: datetime, tz: ZoneInfo, settings: Settings
) -> TelemetryLog | None:
    """The slot's latest MISSED dose if `at` is still before its cutoff (a forced open then
    probably means it was taken late)."""
    log = (
        await session.execute(
            select(TelemetryLog)
            .where(
                TelemetryLog.device_id == device.id,
                TelemetryLog.slot_number == slot_number,
                TelemetryLog.status == DoseStatus.MISSED.value,
                TelemetryLog.scheduled_for <= at,
                TelemetryLog.scheduled_for > at - timedelta(days=1),
            )
            .order_by(TelemetryLog.scheduled_for.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if log is None or at >= await release_cutoff(session, device.id, log, tz, settings):
        return None
    return log
