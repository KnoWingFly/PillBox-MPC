"""Online/offline state derived from real device signals.

Signals that prove a device is alive: a WebSocket heartbeat, a REST
heartbeat, or any authenticated device request (telemetry, config pull).
Each one calls mark_seen().

A device goes OFFLINE when:
  - its WebSocket closes (mark_offline from the WS handler), or
  - no signal arrived for DEVICE_HEARTBEAT_TIMEOUT_SECONDS (sweep(), run by a
    background task every PRESENCE_CHECK_INTERVAL_SECONDS). This is how the
    emulator's Wi-Fi toggle is detected: it simply stops sending.

Notifications (DEVICE_OFFLINE / DEVICE_ONLINE) are decoupled from the state
flip: DEVICE_OFFLINE is written only after the device has stayed offline for
max(DEVICE_OFFLINE_NOTIFY_GRACE_SECONDS, caregiver's
device_offline_after_minutes), and DEVICE_ONLINE only goes to caregivers who
received the DEVICE_OFFLINE for that same outage. A short blip therefore flips
the state but produces no notifications.
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Device, Elderly, Notification
from app.models.enums import Connectivity, NotificationType, Severity
from app.services.notifications import NotificationSpec, load_recipients, notify, ts_key
from app.services.timeutil import zone

logger = logging.getLogger(__name__)

# The longest caregiver preference (1440 min) plus slack; older outages were
# already notified (or never will be), so the sweep does not re-scan them.
_MAX_OFFLINE_NOTIFY_LOOKBACK = timedelta(minutes=1440 + 60)


def device_label(device: Device) -> str:
    return device.device_nickname or device.device_code


def offline_event_key(device_id: UUID, offline_since: datetime) -> str:
    return f"DEVICE_OFFLINE:{device_id}:{ts_key(offline_since)}"


async def mark_seen(session: AsyncSession, device: Device, now: datetime) -> bool:
    """Records a liveness signal. Returns True on an OFFLINE -> ONLINE transition.
    Locks the device row; does not commit."""
    await session.refresh(device, with_for_update=True)
    device.last_heartbeat = now
    if device.status == Connectivity.ONLINE:
        return False

    previous_offline_since = device.offline_since
    device.status = Connectivity.ONLINE.value
    device.online_since = now
    device.offline_since = None
    logger.info(
        "device_online",
        extra={"device_id": str(device.id), "offline_since": str(previous_offline_since)},
    )
    if previous_offline_since is not None and device.elderly_id is not None:
        notified = await session.execute(
            select(Notification.user_id).where(
                Notification.event_key == offline_event_key(device.id, previous_offline_since)
            )
        )
        user_ids = set(notified.scalars().all())
        if user_ids:
            await notify(
                session,
                NotificationSpec(
                    type=NotificationType.DEVICE_ONLINE,
                    severity=Severity.INFO,
                    event_key=f"DEVICE_ONLINE:{device.id}:{ts_key(previous_offline_since)}",
                    elderly_id=device.elderly_id,
                    device_id=device.id,
                    params={"device": device_label(device)},
                ),
                only_user_ids=user_ids,
            )
    return True


async def mark_offline(session: AsyncSession, device_id: UUID, offline_since: datetime, reason: str) -> bool:
    """Conditional flip ONLINE -> OFFLINE (safe against concurrent updates).
    Does not commit."""
    result = await session.execute(
        update(Device)
        .where(Device.id == device_id, Device.status == Connectivity.ONLINE.value)
        .values(status=Connectivity.OFFLINE.value, offline_since=offline_since, online_since=None)
        .returning(Device.id)
        .execution_options(synchronize_session=False)
    )
    flipped = result.scalar_one_or_none() is not None
    if flipped:
        logger.info("device_offline", extra={"device_id": str(device_id), "reason": reason})
    return flipped


async def sweep(session: AsyncSession, now: datetime, settings: Settings) -> None:
    """One presence pass: heartbeat timeouts, then due DEVICE_OFFLINE
    notifications. Commits."""
    cutoff = now - timedelta(seconds=settings.device_heartbeat_timeout_seconds)
    timed_out = await session.execute(
        update(Device)
        .where(
            Device.status == Connectivity.ONLINE.value,
            or_(Device.last_heartbeat.is_(None), Device.last_heartbeat < cutoff),
        )
        # offline_since = last real signal, not the moment we noticed.
        .values(status=Connectivity.OFFLINE.value, offline_since=Device.last_heartbeat, online_since=None)
        .returning(Device.id)
        .execution_options(synchronize_session=False)
    )
    for device_id in timed_out.scalars().all():
        logger.info("device_offline", extra={"device_id": str(device_id), "reason": "heartbeat_timeout"})

    global_grace = timedelta(seconds=settings.device_offline_notify_grace_seconds)
    candidates = await session.execute(
        select(Device)
        .join(Elderly, Elderly.id == Device.elderly_id)
        .where(
            Device.status == Connectivity.OFFLINE.value,
            Device.offline_since.is_not(None),
            Device.offline_since <= now - global_grace,
            Device.offline_since >= now - _MAX_OFFLINE_NOTIFY_LOOKBACK - global_grace,
            Elderly.deleted_at.is_(None),
        )
    )
    for device in candidates.scalars().all():
        offline_since = device.offline_since
        elderly_id = device.elderly_id
        if offline_since is None or elderly_id is None:
            continue
        recipients = await load_recipients(session, elderly_id)
        due = {
            r.user_id
            for r in recipients
            if offline_since <= now - max(global_grace, timedelta(minutes=r.prefs.device_offline_after_minutes))
        }
        if not due:
            continue
        await notify(
            session,
            NotificationSpec(
                type=NotificationType.DEVICE_OFFLINE,
                severity=Severity.WARNING,
                event_key=offline_event_key(device.id, offline_since),
                elderly_id=elderly_id,
                device_id=device.id,
                params={
                    "device": device_label(device),
                    "since": offline_since.astimezone(zone(device.timezone)).strftime("%Y-%m-%d %H:%M"),
                },
            ),
            recipients=recipients,
            only_user_ids=due,
        )
    await session.commit()
