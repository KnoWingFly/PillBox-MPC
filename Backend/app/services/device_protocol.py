"""Device-side REST/WS protocol: authentication, heartbeat, config pull and ack."""

import logging
from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, conflict
from app.core.security import verify_device_secret
from app.models import Device, DeviceStock, Schedule
from app.models.enums import NotificationType, Severity
from app.schemas.device_protocol import (
    ConfigAckResponse,
    ConfigResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    ScheduleConfig,
)
from app.services.notifications import NotificationSpec, notify, ts_key
from app.services.presence import device_label, mark_seen
from app.services.timeutil import as_aware, zone

logger = logging.getLogger(__name__)

_LOW_BATTERY_HYSTERESIS = 5


def device_key_invalid() -> AppError:
    return AppError(401, "DEVICE_KEY_INVALID", "Device key is missing or invalid")


async def find_device(session: AsyncSession, device_ref: str) -> Device | None:
    """device_ref is a device_code (what the device knows) or the device UUID."""
    try:
        as_uuid = UUID(device_ref)
    except ValueError:
        as_uuid = None
    stmt = select(Device).where(Device.id == as_uuid) if as_uuid else select(Device).where(Device.device_code == device_ref)
    return (await session.execute(stmt)).scalar_one_or_none()


async def authenticate_device(session: AsyncSession, device_ref: str, secret: str | None) -> Device:
    device = await find_device(session, device_ref)
    # verify_device_secret runs in constant time and also when device is None.
    if not verify_device_secret(secret, device.device_secret_hash if device else None) or device is None:
        logger.warning("device_auth_failed", extra={"device_ref": device_ref})
        raise device_key_invalid()
    return device


async def process_heartbeat(
    session: AsyncSession, device: Device, hb: HeartbeatRequest, now: datetime, settings: Settings
) -> HeartbeatResponse:
    """Shared by REST POST /heartbeat and WebSocket {"type": "heartbeat"}. Commits."""
    await mark_seen(session, device, now)  # must run first: it refreshes the row
    tz = zone(device.timezone)

    device.battery_percentage = hb.battery_percent
    device.wifi_rssi_dbm = hb.wifi_rssi_dbm
    if hb.rtc_time is not None:
        device.rtc_time = as_aware(hb.rtc_time, tz)
        device.rtc_reported_at = now
    if hb.rtc_backup_active is not None:
        device.rtc_backup_active = hb.rtc_backup_active
    if hb.chambers:
        device.chamber_doors = [{"slot_number": c.slot_number, "door": c.door} for c in hb.chambers]
    if hb.config_version_applied is not None:
        device.config_version_applied = hb.config_version_applied

    # The device holds the physical sachets, so its count is authoritative.
    # One multi-row upsert: each DB round-trip is expensive on a remote database.
    latest_count = {c.slot_number: c.stock_count for c in hb.chambers if c.stock_count is not None}
    stocks = [
        {"device_id": device.id, "slot_number": slot, "remaining_units": count}
        for slot, count in latest_count.items()
    ]
    if stocks:
        stmt = insert(DeviceStock).values(stocks)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[DeviceStock.device_id, DeviceStock.slot_number],
                set_={"remaining_units": stmt.excluded.remaining_units, "updated_at": now},
            )
        )

    await _check_low_battery(session, device, now, settings)
    await session.commit()

    applied = device.config_version_applied or 0
    return HeartbeatResponse(
        server_time=now,
        latest_config_version=device.config_version,
        config_update_available=device.config_version > applied,
        heartbeat_interval_seconds=settings.device_heartbeat_interval_seconds,
        is_paired=device.elderly_id is not None,
    )


async def _check_low_battery(session: AsyncSession, device: Device, now: datetime, settings: Settings) -> None:
    battery = device.battery_percentage
    if battery is None:
        return
    threshold = settings.low_battery_threshold_percent
    if battery >= threshold + _LOW_BATTERY_HYSTERESIS:
        device.low_battery_notified_at = None  # recovered; next drop notifies again
        return
    if battery > threshold or device.low_battery_notified_at is not None or device.elderly_id is None:
        return
    device.low_battery_notified_at = now
    await notify(
        session,
        NotificationSpec(
            type=NotificationType.LOW_BATTERY,
            severity=Severity.WARNING,
            event_key=f"LOW_BATTERY:{device.id}:{ts_key(now)}",
            elderly_id=device.elderly_id,
            device_id=device.id,
            params={"device": device_label(device), "battery": battery},
        ),
    )


def hhmm(value: time) -> str:
    return value.strftime("%H:%M")


async def build_config(session: AsyncSession, device: Device) -> ConfigResponse:
    rows = await session.execute(
        select(Schedule)
        .where(Schedule.device_id == device.id, Schedule.deleted_at.is_(None))
        .order_by(Schedule.slot_number)
    )
    return ConfigResponse(
        config_version=device.config_version,
        timezone=device.timezone,
        chime_volume_level=device.chime_volume_level,
        is_refill_mode=device.is_refill_mode,
        schedules=[
            ScheduleConfig(
                schedule_id=str(s.id),
                slot_number=s.slot_number,
                window_start=hhmm(s.window_start),
                window_end=hhmm(s.window_end),
                tolerance_minutes=s.tolerance_minutes,
                days_of_week=sorted(s.days_of_week),
                active=s.is_active,
                medication_name=s.medication_name,
                dosage_info=s.dosage_info,
            )
            for s in rows.scalars().all()
        ],
    )


async def ack_config(
    session: AsyncSession, device: Device, config_version: int, applied_at: datetime | None, now: datetime
) -> ConfigAckResponse:
    if config_version > device.config_version:
        raise conflict(
            "CONFIG_VERSION_UNKNOWN",
            f"Config version {config_version} was never issued (latest is {device.config_version})",
        )
    tz = zone(device.timezone)
    # Ignore stale acks (an older version acked after a newer one).
    if device.config_version_applied is None or config_version >= device.config_version_applied:
        device.config_version_applied = config_version
        device.config_applied_at = as_aware(applied_at, tz) if applied_at else now
    await session.commit()
    logger.info("config_ack", extra={"device_id": str(device.id), "config_version": config_version})
    return ConfigAckResponse(acknowledged=True, config_version_applied=config_version)


def is_fresh(occurred_at: datetime, now: datetime, settings: Settings) -> bool:
    return occurred_at >= now - timedelta(seconds=2 * settings.device_heartbeat_interval_seconds)
