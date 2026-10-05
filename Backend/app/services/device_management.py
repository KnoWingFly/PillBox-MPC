"""Caregiver-side device management: QR pairing, PIN join/change, settings,
unpairing, live status, clock, and commands (alarm, time sync)."""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, conflict, not_found, unprocessable
from app.core.security import hash_pin, verify_pin
from app.models import Device, DeviceEvent, DeviceStock, Elderly, Schedule, TelemetryLog, User, UserElderlyRole
from app.models.enums import ALL_ROLES, EDITOR_ROLES, ChimeVolume, Connectivity, DoseStatus, Role
from app.schemas.devices import (
    ChamberDoor,
    ClockOut,
    CommandResultOut,
    DeviceDetail,
    DeviceEventOut,
    DeviceListItem,
    DeviceSlotOut,
    DeviceStatusOut,
    DeviceUpdateIn,
    DeviceUpdateOut,
    JoinDeviceOut,
    PairDeviceIn,
    PairDeviceOut,
    PairingScanOut,
    SlotLayoutOut,
)
from app.services.access import get_device_for_user, require_role
from app.services.connection_manager import (
    CommandAck,
    CommandError,
    CommandTimeoutError,
    DeviceCommand,
    DeviceDisconnectedError,
    DeviceNotConnectedError,
    connection_manager,
)
from app.services.pin_attempts import pin_limiter
from app.services.slots import SLOT_NUMBERS, all_slots
from app.services.timeutil import as_aware, is_valid_timezone, zone

logger = logging.getLogger(__name__)

_PIN = re.compile(r"^\d{4}$")
DEFAULT_TIMEZONE = "Asia/Jakarta"


# --- helpers ------------------------------------------------------------------

def parse_qr_payload(raw: str) -> str:
    """ASSUMPTION: the QR printed on a device encodes its device_code, either
    raw ("PB-1A2B3C4D"), as a URI ("pillcare://device/PB-1A2B3C4D" - the format
    returned by provisioning), or as JSON ({"device_code": "..."})."""
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError:
            return raw
        code = data.get("device_code") if isinstance(data, dict) else None
        return str(code).strip() if code else raw
    if "://" in raw:
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        for key in ("device_code", "code"):
            if query.get(key):
                return query[key][0].strip()
        segments = [s for s in parsed.path.split("/") if s]
        if segments:
            return segments[-1]
        return parsed.netloc
    return raw


def check_pin_format(pin: str) -> None:
    if not _PIN.match(pin):
        raise unprocessable("DEVICE_PIN_INVALID", "Device PIN must be exactly 4 digits")


def wifi_strength(rssi: int | None) -> Literal["LEMAH", "SEDANG", "KUAT"] | None:
    if rssi is None:
        return None
    if rssi >= -60:
        return "KUAT"
    if rssi >= -75:
        return "SEDANG"
    return "LEMAH"


def battery_days(device: Device, settings: Settings) -> float | None:
    if device.battery_percentage is None or settings.battery_rated_days is None:
        return None
    return round(settings.battery_rated_days * device.battery_percentage / 100.0, 1)


def slot_layouts() -> list[SlotLayoutOut]:
    return [
        SlotLayoutOut(slot_number=s.slot_number, row=s.row, meal_relation=s.meal_relation, day_period=s.day_period)
        for s in all_slots()
    ]


async def bump_config(session: AsyncSession, device: Device) -> int:
    device.config_version = device.config_version + 1
    await session.flush()
    return device.config_version


async def notify_config_changed(device_id: UUID, config_version: int) -> bool:
    """Best effort: tells a WebSocket-connected device to pull GET /config now.
    REST-only devices learn it from the next heartbeat (config_update_available)."""
    return await connection_manager.notify(
        device_id, DeviceCommand.SCHEDULE_UPDATED, {"config_version": config_version}
    )


async def _check_pin(user_id: UUID, device: Device, pin: str, settings: Settings, error_code: str) -> None:
    key = f"{user_id}:{device.id}"
    pin_limiter.check(key, settings.pin_max_attempts, settings.pin_lockout_seconds)
    if not await asyncio.to_thread(verify_pin, pin, device.device_pin_hash):
        pin_limiter.record_failure(key)
        raise AppError(401, error_code, "Device PIN is incorrect")
    pin_limiter.reset(key)


def command_error_to_app_error(exc: CommandError, device: Device) -> AppError:
    if isinstance(exc, DeviceNotConnectedError):
        if device.status == Connectivity.ONLINE:
            return conflict(
                "DEVICE_COMMAND_CHANNEL_UNAVAILABLE",
                "Device is online (REST heartbeat) but has no WebSocket command channel open",
            )
        return conflict("DEVICE_OFFLINE", "Device is offline; the command was not sent")
    if isinstance(exc, DeviceDisconnectedError):
        return AppError(502, "DEVICE_DISCONNECTED", "Device disconnected before acknowledging the command")
    if isinstance(exc, CommandTimeoutError):
        return AppError(504, "DEVICE_ACK_TIMEOUT", "Device did not acknowledge the command in time")
    return AppError(502, "DEVICE_COMMAND_FAILED", "Device command failed")


async def send_command_or_raise(
    device: Device, command: DeviceCommand, payload: dict[str, Any], settings: Settings
) -> CommandAck:
    try:
        ack = await connection_manager.send_command(
            device.id, command, payload, timeout=settings.command_ack_timeout_seconds
        )
    except CommandError as exc:
        raise command_error_to_app_error(exc, device) from exc
    if not ack.ok:
        raise AppError(
            502, "DEVICE_REJECTED_COMMAND", "Device rejected the command", details={"error": ack.error}
        )
    return ack


async def drop_undecided_doses(session: AsyncSession, *, device_id: UUID | None = None, schedule_id: UUID | None = None) -> None:
    """PENDING dose rows are not history yet; when their schedule/device goes
    away they are removed so the rules engine does not report them missed."""
    stmt = delete(TelemetryLog).where(TelemetryLog.status == DoseStatus.PENDING.value)
    if device_id is not None:
        stmt = stmt.where(TelemetryLog.device_id == device_id)
    if schedule_id is not None:
        stmt = stmt.where(TelemetryLog.schedule_id == schedule_id)
    await session.execute(stmt)


async def unpair(session: AsyncSession, device: Device, now: datetime) -> None:
    """Releases the device so it can be paired again (does not commit)."""
    await session.execute(
        update(Schedule)
        .where(Schedule.device_id == device.id, Schedule.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    await drop_undecided_doses(session, device_id=device.id)
    device.elderly_id = None
    device.device_pin_hash = None
    device.pin_updated_at = None
    device.paired_at = None
    device.device_nickname = None
    device.is_refill_mode = False
    await bump_config(session, device)


# --- pairing ---------------------------------------------------------------------

async def scan(session: AsyncSession, raw_payload: str) -> PairingScanOut:
    code = parse_qr_payload(raw_payload)
    device = (await session.execute(select(Device).where(Device.device_code == code))).scalar_one_or_none()
    if device is None:
        raise not_found("QR_CODE_NOT_RECOGNIZED", "QR code is not a known PillCare device")
    elderly_name = None
    if device.elderly_id is not None:
        elderly = await session.get(Elderly, device.elderly_id)
        if elderly is not None and elderly.deleted_at is None:
            elderly_name = elderly.nickname or elderly.full_name
    return PairingScanOut(
        device_id=device.id, is_registered=device.elderly_id is not None, elderly_name_if_owned=elderly_name
    )


async def pair(session: AsyncSession, user: User, body: PairDeviceIn, now: datetime) -> PairDeviceOut:
    check_pin_format(body.device_pin)
    code = parse_qr_payload(body.device_qr_payload)
    device = (
        await session.execute(select(Device).where(Device.device_code == code).with_for_update())
    ).scalar_one_or_none()
    if device is None:
        raise not_found("QR_CODE_NOT_RECOGNIZED", "QR code is not a known PillCare device")
    if device.elderly_id is not None:
        raise conflict("DEVICE_ALREADY_PAIRED", "Device is already paired; join it with its PIN instead")
    # ASSUMPTION: pairing to an elderly requires OWNER/ADMIN on that elderly
    # (roles are elderly-level; the elderly creator is already its OWNER).
    await require_role(session, user.id, body.elderly_id, EDITOR_ROLES)

    timezone = body.timezone or (user.timezone if is_valid_timezone(user.timezone) else DEFAULT_TIMEZONE)
    device.elderly_id = body.elderly_id
    device.device_nickname = body.device_nickname
    device.timezone = timezone
    device.device_pin_hash = await asyncio.to_thread(hash_pin, body.device_pin)
    device.pin_updated_at = now
    device.paired_at = now
    device.is_refill_mode = False
    version = await bump_config(session, device)
    await session.execute(
        insert(DeviceStock)
        .values([{"device_id": device.id, "slot_number": n, "remaining_units": 0} for n in SLOT_NUMBERS])
        .on_conflict_do_nothing(index_elements=[DeviceStock.device_id, DeviceStock.slot_number])
    )
    await session.commit()
    logger.info("device_paired", extra={"device_id": str(device.id), "elderly_id": str(body.elderly_id)})
    await notify_config_changed(device.id, version)
    return PairDeviceOut(
        id=device.id,
        device_nickname=device.device_nickname,
        elderly_id=body.elderly_id,
        connectivity=Connectivity(device.status),
        config_version=version,
        paired_at=now,
        slots=slot_layouts(),
    )


async def join(
    session: AsyncSession, user: User, device_id: UUID, pin: str, settings: Settings, now: datetime
) -> JoinDeviceOut:
    device = await session.get(Device, device_id)
    if device is None or device.elderly_id is None:
        raise not_found(message="Device not found")
    await _check_pin(user.id, device, pin, settings, "DEVICE_PIN_INCORRECT")
    elderly_id = device.elderly_id
    existing = (
        await session.execute(
            select(UserElderlyRole).where(
                UserElderlyRole.user_id == user.id, UserElderlyRole.elderly_id == elderly_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return JoinDeviceOut(
            device_id=device.id, elderly_id=elderly_id, my_role=Role(existing.role), joined_at=existing.created_at
        )
    role = UserElderlyRole(user_id=user.id, elderly_id=elderly_id, role=Role.PEMANTAU.value, created_at=now)
    session.add(role)
    await session.commit()
    logger.info("caregiver_joined_device", extra={"device_id": str(device.id), "user_id": str(user.id)})
    return JoinDeviceOut(device_id=device.id, elderly_id=elderly_id, my_role=Role.PEMANTAU, joined_at=now)


async def change_pin(
    session: AsyncSession, user: User, device_id: UUID, current: str, new: str, settings: Settings, now: datetime
) -> datetime:
    device, _ = await get_device_for_user(session, user.id, device_id, {Role.OWNER}, for_update=True)
    check_pin_format(new)
    await _check_pin(user.id, device, current, settings, "CURRENT_PIN_INCORRECT")
    device.device_pin_hash = await asyncio.to_thread(hash_pin, new)
    device.pin_updated_at = now
    await session.commit()
    return now


# --- reads --------------------------------------------------------------------------

async def list_devices(
    session: AsyncSession, user: User, elderly_id: UUID | None, settings: Settings
) -> list[DeviceListItem]:
    stmt = (
        select(Device, Elderly)
        .join(Elderly, Elderly.id == Device.elderly_id)
        .join(UserElderlyRole, UserElderlyRole.elderly_id == Elderly.id)
        .where(UserElderlyRole.user_id == user.id, Elderly.deleted_at.is_(None))
        .order_by(Elderly.full_name, Device.device_nickname)
    )
    if elderly_id is not None:
        stmt = stmt.where(Device.elderly_id == elderly_id)
    rows = (await session.execute(stmt)).all()
    return [
        DeviceListItem(
            id=d.id,
            device_code=d.device_code,
            device_nickname=d.device_nickname,
            elderly_id=e.id,
            elderly_nickname=e.nickname or e.full_name,
            connectivity=Connectivity(d.status),
            battery_percent=d.battery_percentage,
            estimated_battery_days_remaining=battery_days(d, settings),
            last_seen_at=d.last_heartbeat,
        )
        for d, e in rows
    ]


async def active_slots(session: AsyncSession, device_id: UUID) -> set[int]:
    rows = await session.execute(
        select(Schedule.slot_number).where(
            Schedule.device_id == device_id, Schedule.deleted_at.is_(None), Schedule.is_active.is_(True)
        )
    )
    return set(rows.scalars().all())


async def detail(session: AsyncSession, user: User, device_id: UUID) -> DeviceDetail:
    device, role = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    active = await active_slots(session, device.id)
    assert device.elderly_id is not None
    return DeviceDetail(
        id=device.id,
        device_code=device.device_code,
        device_nickname=device.device_nickname,
        elderly_id=device.elderly_id,
        my_role=role,
        timezone=device.timezone,
        auto_sync_timezone=device.auto_sync_timezone,
        chime_volume_level=ChimeVolume(device.chime_volume_level),
        config_version=device.config_version,
        config_version_applied=device.config_version_applied,
        is_refill_mode=device.is_refill_mode,
        connectivity=Connectivity(device.status),
        slots=[
            DeviceSlotOut(
                slot_number=s.slot_number, row=s.row, meal_relation=s.meal_relation,
                day_period=s.day_period, has_active_schedule=s.slot_number in active,
            )
            for s in all_slots()
        ],
    )


async def update_settings(
    session: AsyncSession, user: User, device_id: UUID, body: DeviceUpdateIn
) -> DeviceUpdateOut:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    changes = body.model_dump(exclude_unset=True)
    if "elderly_id" in changes and changes["elderly_id"] is None:
        raise unprocessable("VALIDATION_ERROR", "elderly_id cannot be null; unpair with DELETE instead")
    config_changed = False
    for field in ("chime_volume_level", "timezone", "auto_sync_timezone"):
        if field in changes and changes[field] is not None and getattr(device, field) != changes[field]:
            setattr(device, field, changes[field])
            config_changed = True
    if changes.get("device_nickname") is not None:
        device.device_nickname = changes["device_nickname"]
    target = changes.get("elderly_id")
    if target is not None and target != device.elderly_id:
        await require_role(session, user.id, target, EDITOR_ROLES)
        await drop_undecided_doses(session, device_id=device.id)
        device.elderly_id = target
    if config_changed:
        await bump_config(session, device)
    await session.commit()
    await session.refresh(device)
    if config_changed:
        await notify_config_changed(device.id, device.config_version)
    assert device.elderly_id is not None
    return DeviceUpdateOut(
        id=device.id,
        device_nickname=device.device_nickname,
        chime_volume_level=ChimeVolume(device.chime_volume_level),
        timezone=device.timezone,
        auto_sync_timezone=device.auto_sync_timezone,
        elderly_id=device.elderly_id,
        config_version=device.config_version,
        updated_at=device.updated_at,
    )


async def remove(session: AsyncSession, user: User, device_id: UUID, now: datetime) -> None:
    device, _ = await get_device_for_user(session, user.id, device_id, {Role.OWNER}, for_update=True)
    await unpair(session, device, now)
    await session.commit()
    logger.info("device_unpaired", extra={"device_id": str(device.id)})


async def status(session: AsyncSession, user: User, device_id: UUID, settings: Settings) -> DeviceStatusOut:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    doors = device.chamber_doors or []
    return DeviceStatusOut(
        device_id=device.id,
        connectivity=Connectivity(device.status),
        last_seen_at=device.last_heartbeat,
        online_since=device.online_since,
        offline_since=device.offline_since,
        wifi_strength=wifi_strength(device.wifi_rssi_dbm),
        wifi_rssi_dbm=device.wifi_rssi_dbm,
        battery_percent=device.battery_percentage,
        estimated_battery_days_remaining=battery_days(device, settings),
        rtc_backup_active=device.rtc_backup_active,
        command_channel_connected=connection_manager.is_connected(device.id),
        chambers=[ChamberDoor(slot_number=int(c["slot_number"]), door=c["door"]) for c in doors],
    )


def _clock_values(device: Device, now: datetime) -> tuple[datetime | None, float | None]:
    if device.rtc_time is None or device.rtc_reported_at is None:
        return None, None
    drift = (device.rtc_time - device.rtc_reported_at).total_seconds()
    return now + timedelta(seconds=drift), round(drift, 1)


async def clock(session: AsyncSession, user: User, device_id: UUID, settings: Settings, now: datetime) -> ClockOut:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    internal, drift = _clock_values(device, now)
    return ClockOut(
        device_id=device.id,
        device_internal_time=internal.astimezone(zone(device.timezone)) if internal else None,
        server_time=now,
        drift_seconds=drift,
        is_accurate=None if drift is None else abs(drift) <= settings.clock_drift_tolerance_seconds,
        auto_sync_timezone=device.auto_sync_timezone,
        reported_at=device.rtc_reported_at,
    )


async def calibrate(
    session: AsyncSession, user: User, device_id: UUID, pin: str, settings: Settings, now: datetime
) -> tuple[Device, CommandAck]:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES)
    await _check_pin(user.id, device, pin, settings, "DEVICE_PIN_INCORRECT")
    await session.commit()  # end the read transaction before waiting on the device
    ack = await send_command_or_raise(
        device,
        DeviceCommand.TIME_SYNC,
        {"server_time": now.isoformat(), "timezone": device.timezone},
        settings,
    )
    reported = (ack.result or {}).get("device_time_after")
    if isinstance(reported, str):
        try:
            device_time = as_aware(datetime.fromisoformat(reported), zone(device.timezone))
        except ValueError:
            device_time = None
        if device_time is not None:
            await session.refresh(device, with_for_update=True)
            device.rtc_time = device_time
            device.rtc_reported_at = ack.acked_at
            await session.commit()
    return device, ack


async def trigger_alarm(
    session: AsyncSession, user: User, device_id: UUID, slot_number: int | None, duration_seconds: int, settings: Settings
) -> CommandResultOut:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES)
    await session.commit()  # do not hold a transaction while waiting for the ack
    ack = await send_command_or_raise(
        device,
        DeviceCommand.TRIGGER_ALARM,
        {"slot_number": slot_number, "duration_seconds": duration_seconds, "reason": "caregiver_request"},
        settings,
    )
    logger.info("alarm_triggered", extra={"device_id": str(device.id), "user_id": str(user.id)})
    return CommandResultOut(
        device_id=device.id,
        command=DeviceCommand.TRIGGER_ALARM.value,
        command_id=ack.command_id,
        acknowledged=True,
        acked_at=ack.acked_at,
        result=ack.result,
    )


async def list_events(
    session: AsyncSession, user: User, device_id: UUID, offset: int, limit: int
) -> tuple[list[DeviceEventOut], int]:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    total = (
        await session.execute(select(func.count()).select_from(DeviceEvent).where(DeviceEvent.device_id == device.id))
    ).scalar_one()
    rows = await session.execute(
        select(DeviceEvent)
        .where(DeviceEvent.device_id == device.id)
        .order_by(DeviceEvent.occurred_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        DeviceEventOut(
            event_id=e.event_id, event_type=e.event_type, slot_number=e.slot_number,
            occurred_at=e.occurred_at, received_at=e.received_at, outcome=e.outcome,
            reject_reason=e.reject_reason, telemetry_log_id=e.telemetry_log_id,
        )
        for e in rows.scalars().all()
    ]
    return items, total

