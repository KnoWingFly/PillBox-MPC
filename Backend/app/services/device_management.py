"""Caregiver-side device management: QR pairing, PIN join/change, settings,
unpairing, live status, clock, and commands (alarm, time sync)."""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timing
from app.core.config import Settings
from app.core.errors import AppError, conflict, not_found, unprocessable
from app.core.security import hash_pin, verify_pin
from app.models import Device, DeviceEvent, DeviceStock, Elderly, Schedule, TelemetryLog, User, UserElderlyRole
from app.models.enums import ALL_ROLES, EDITOR_ROLES, AttemptScope, ChimeVolume, Connectivity, DoseStatus, Role
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
from app.services import pin_attempts, stock_cache
from app.services.access import get_device_for_user, require_role
from app.services.app_hub import queue_roles_changed
from app.services.connection_manager import (
    CommandAck,
    CommandError,
    CommandTimeoutError,
    DeviceCommand,
    DeviceDisconnectedError,
    DeviceNotConnectedError,
    connection_manager,
)
from app.services.device_clock import extrapolated
from app.services.slots import SLOT_NUMBERS, all_slots
from app.services.timeutil import as_aware, is_valid_timezone, zone

logger = logging.getLogger(__name__)

# `reason` sent with alarm commands started from the app (docs/DEVICE_CONTRACT.md §3).
ALARM_REASON_CAREGIVER = "caregiver_request"

_PIN = re.compile(r"^\d{4}$")


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


def wifi_strength(rssi: int | None, settings: Settings) -> Literal["LEMAH", "SEDANG", "KUAT"] | None:
    if rssi is None:
        return None
    if rssi >= settings.wifi_rssi_strong_dbm:
        return "KUAT"
    if rssi >= settings.wifi_rssi_medium_dbm:
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


async def _check_pin(
    user_id: UUID,
    device: Device,
    pin: str,
    settings: Settings,
    error_code: str,
    scope: AttemptScope = AttemptScope.DEVICE_PIN,
) -> None:
    """Counted per device across all users (services/pin_attempts.py), before scrypt runs, so
    parallel guesses cannot get past the limit. `join` (callers who are not caregivers yet) uses
    its own counter, DEVICE_PIN_JOIN: strangers guessing cannot lock the caregivers out of their
    own PIN actions (change PIN, calibrate, late release)."""
    check_pin_format(pin)
    key = str(device.id)
    await pin_attempts.register_attempt(
        scope, key, settings.pin_max_attempts, settings.pin_lockout_seconds,
        "Too many incorrect PIN attempts, try again later",
    )
    if not await asyncio.to_thread(verify_pin, pin, device.device_pin_hash):
        raise AppError(401, error_code, "Device PIN is incorrect")
    await pin_attempts.reset(scope, key)


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
    stock_cache.forget(device.id)
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

async def _count_lookup(user: User, settings: Settings) -> None:
    """Device-code lookups are rate-limited per user: the answers reveal which codes exist
    (Mobile/BACKEND_HANDOFF.md item 1). Shared by POST /pairing/scan and POST /devices."""
    await pin_attempts.register_attempt(
        AttemptScope.PAIRING_SCAN, str(user.id), settings.pairing_scan_max_attempts,
        settings.pairing_scan_window_seconds, "Too many device code lookups, try again later",
    )


async def scan(session: AsyncSession, user: User, raw_payload: str, settings: Settings) -> PairingScanOut:
    await session.commit()  # the user lookup's connection goes back before counting takes one
    await _count_lookup(user, settings)
    code = parse_qr_payload(raw_payload)
    device = (await session.execute(select(Device).where(Device.device_code == code))).scalar_one_or_none()
    if device is None:
        raise not_found("QR_CODE_NOT_RECOGNIZED", "QR code is not a known PillCare device")
    elderly_name = None
    if device.elderly_id is not None:
        # Only a caregiver of that elderly sees the name; anyone else holding the QR code (or
        # guessing codes) learns only that the device is registered (BACKEND_HANDOFF §2).
        row = (
            await session.execute(
                select(Elderly)
                .join(UserElderlyRole, UserElderlyRole.elderly_id == Elderly.id)
                .where(
                    Elderly.id == device.elderly_id,
                    Elderly.deleted_at.is_(None),
                    UserElderlyRole.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            elderly_name = row.nickname or row.full_name
    return PairingScanOut(
        device_id=device.id, is_registered=device.elderly_id is not None, elderly_name_if_owned=elderly_name
    )


async def pair(
    session: AsyncSession, user: User, body: PairDeviceIn, settings: Settings, now: datetime
) -> PairDeviceOut:
    check_pin_format(body.device_pin)
    code = parse_qr_payload(body.device_qr_payload)
    # scrypt takes tens of ms: hash before taking the row lock, with no transaction (and so no
    # pooled connection) held. The caller's user lookup opened one; nothing was written yet.
    # Committed before counting too, which uses a connection of its own.
    await session.commit()
    await _count_lookup(user, settings)  # an unknown code answers 404: same enumeration guard as scan
    pin_hash = await asyncio.to_thread(hash_pin, body.device_pin)
    device = (
        await session.execute(select(Device).where(Device.device_code == code).with_for_update(key_share=True))
    ).scalar_one_or_none()
    if device is None:
        raise not_found("QR_CODE_NOT_RECOGNIZED", "QR code is not a known PillCare device")
    if device.elderly_id is not None:
        raise conflict("DEVICE_ALREADY_PAIRED", "Device is already paired; join it with its PIN instead")
    # ASSUMPTION: pairing to an elderly requires OWNER/ADMIN on that elderly
    # (roles are elderly-level; the elderly creator is already its OWNER).
    await require_role(session, user.id, body.elderly_id, EDITOR_ROLES)

    profile_tz = user.timezone if is_valid_timezone(user.timezone) else settings.default_device_timezone
    timezone = body.timezone or profile_tz
    device.elderly_id = body.elderly_id
    device.device_nickname = body.device_nickname
    device.timezone = timezone
    device.device_pin_hash = pin_hash
    device.pin_updated_at = now
    device.paired_at = now
    device.is_refill_mode = False
    version = await bump_config(session, device)
    stock_cache.forget(device.id)
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
    await session.commit()  # read only so far: hold no pooled connection during the slow PIN check
    await _check_pin(user.id, device, pin, settings, "DEVICE_PIN_INCORRECT", AttemptScope.DEVICE_PIN_JOIN)
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
    queue_roles_changed(session, user.id)
    await session.commit()
    logger.info("caregiver_joined_device", extra={"device_id": str(device.id), "user_id": str(user.id)})
    return JoinDeviceOut(device_id=device.id, elderly_id=elderly_id, my_role=Role.PEMANTAU, joined_at=now)


async def change_pin(
    session: AsyncSession, user: User, device_id: UUID, current: str, new: str, settings: Settings, now: datetime
) -> datetime:
    device, _ = await get_device_for_user(session, user.id, device_id, {Role.OWNER})
    check_pin_format(new)
    checked_hash = device.device_pin_hash
    # Both scrypt calls run with no transaction or row lock held; the row is locked only to write.
    await session.commit()
    await _check_pin(user.id, device, current, settings, "CURRENT_PIN_INCORRECT")
    new_hash = await asyncio.to_thread(hash_pin, new)
    await session.refresh(device, with_for_update={"key_share": True})
    if device.device_pin_hash != checked_hash:
        # The PIN changed meanwhile (another request): check against the PIN now in force.
        await _check_pin(user.id, device, current, settings, "CURRENT_PIN_INCORRECT")
    device.device_pin_hash = new_hash
    device.pin_updated_at = now
    await session.commit()
    return now


# --- reads --------------------------------------------------------------------------

async def list_devices(
    session: AsyncSession, user: User, elderly_id: UUID | None, settings: Settings, offset: int, limit: int
) -> tuple[list[DeviceListItem], int]:
    """One page and the total, in one query (the total rides along as a window count)."""
    stmt = (
        select(Device, Elderly, func.count().over().label("total"))
        .join(Elderly, Elderly.id == Device.elderly_id)
        .join(UserElderlyRole, UserElderlyRole.elderly_id == Elderly.id)
        .where(UserElderlyRole.user_id == user.id, Elderly.deleted_at.is_(None))
        .order_by(Elderly.full_name, Device.device_nickname, Device.id)
        .offset(offset)
        .limit(limit)
    )
    if elderly_id is not None:
        stmt = stmt.where(Device.elderly_id == elderly_id)
    rows = (await session.execute(stmt)).all()
    total = rows[0].total if rows else await _count_devices(session, user, elderly_id, offset)
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
        for d, e, _ in rows
    ], total


async def _count_devices(session: AsyncSession, user: User, elderly_id: UUID | None, offset: int) -> int:
    """Total for an empty page: 0 on the first page, else a count (a page past the end)."""
    if offset == 0:
        return 0
    stmt = (
        select(func.count())
        .select_from(Device)
        .join(Elderly, Elderly.id == Device.elderly_id)
        .join(UserElderlyRole, UserElderlyRole.elderly_id == Elderly.id)
        .where(UserElderlyRole.user_id == user.id, Elderly.deleted_at.is_(None))
    )
    if elderly_id is not None:
        stmt = stmt.where(Device.elderly_id == elderly_id)
    return int(await session.scalar(stmt) or 0)


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
    if device.elderly_id is None:  # get_device_for_user only returns paired devices
        raise not_found(message="Device not found")
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
    if config_changed:
        await notify_config_changed(device.id, device.config_version)
    if device.elderly_id is None:  # get_device_for_user only returns paired devices
        raise not_found(message="Device not found")
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
    # A WebSocket device drops its schedules now instead of at its next heartbeat.
    await notify_config_changed(device.id, device.config_version)


async def status(session: AsyncSession, user: User, device_id: UUID, settings: Settings) -> DeviceStatusOut:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    return build_status(device, settings)


def build_status(device: Device, settings: Settings) -> DeviceStatusOut:
    """GET /devices/{id}/status body from an already-loaded row (no DB access);
    also pushed to app sockets after a device change (services/app_hub.py)."""
    doors = device.chamber_doors or []
    device_time = extrapolated(device, datetime.now(UTC))
    return DeviceStatusOut(
        device_id=device.id,
        connectivity=Connectivity(device.status),
        last_seen_at=device.last_heartbeat,
        online_since=device.online_since,
        offline_since=device.offline_since,
        wifi_strength=wifi_strength(device.wifi_rssi_dbm, settings),
        wifi_rssi_dbm=device.wifi_rssi_dbm,
        battery_percent=device.battery_percentage,
        estimated_battery_days_remaining=battery_days(device, settings),
        rtc_backup_active=device.rtc_backup_active,
        command_channel_connected=connection_manager.is_connected(device.id),
        chambers=[ChamberDoor(slot_number=int(c["slot_number"]), door=c["door"]) for c in doors],
        device_time=device_time.astimezone(zone(device.timezone)) if device_time else None,
        clock_speed=(device.rtc_speed or 1.0) if device_time else None,
        follow_device_clock=settings.follow_device_clock,
    )


def _clock_values(device: Device, now: datetime) -> tuple[datetime | None, float | None]:
    internal = extrapolated(device, now)
    if internal is None:
        return None, None
    return internal, round((internal - now).total_seconds(), 1)


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
    await session.commit()  # end the read transaction before the PIN check and the device wait
    await _check_pin(user.id, device, pin, settings, "DEVICE_PIN_INCORRECT")
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
            await session.refresh(device, with_for_update={"key_share": True})
            device.rtc_time = device_time
            device.rtc_reported_at = ack.acked_at
            device.rtc_speed = 1.0  # time_sync also puts the emulator's lab clock back to 1x
            await session.commit()
    return device, ack


async def trigger_alarm(
    session: AsyncSession, user: User, device_id: UUID, slot_number: int | None, duration_seconds: int, settings: Settings
) -> CommandResultOut:
    payload = {"slot_number": slot_number, "duration_seconds": duration_seconds, "reason": ALARM_REASON_CAREGIVER}
    return await _alarm_command(session, user, device_id, DeviceCommand.TRIGGER_ALARM, payload, settings)


async def stop_alarm(session: AsyncSession, user: User, device_id: UUID, settings: Settings) -> CommandResultOut:
    """Silences an alarm a caregiver started (trigger_alarm). A dose reminder keeps ringing:
    the device ignores stop_alarm for it (docs/DEVICE_CONTRACT.md §3)."""
    payload = {"reason": ALARM_REASON_CAREGIVER}
    return await _alarm_command(session, user, device_id, DeviceCommand.STOP_ALARM, payload, settings)


async def _alarm_command(
    session: AsyncSession,
    user: User,
    device_id: UUID,
    command: DeviceCommand,
    payload: dict[str, Any],
    settings: Settings,
) -> CommandResultOut:
    """OWNER/ADMIN; succeeds only after the device acks (errors: command_error_to_app_error)."""
    started = timing.now_ms()
    timing.log_timing("app_to_iot", "backend_received", command=command.value)
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES)
    await session.commit()  # do not hold a transaction while waiting for the ack
    timing.log_timing("app_to_iot", "access_checked", db_ms=timing.since_ms(started))
    ack = await send_command_or_raise(device, command, payload, settings)
    logger.info("alarm_command", extra={"device_id": str(device.id), "user_id": str(user.id), "command": command.value})
    return CommandResultOut(
        device_id=device.id,
        command=command.value,
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

