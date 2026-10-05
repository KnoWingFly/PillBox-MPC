"""Caregiver (mobile app) device routes. Auth: Bearer access token."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, PaginationDep, SettingsDep
from app.schemas.devices import (
    AlarmIn,
    CalibrateIn,
    CalibrateOut,
    ChangePinIn,
    ChangePinOut,
    ClockOut,
    CommandResultOut,
    DeviceDetail,
    DeviceEventPage,
    DeviceList,
    DeviceStatusOut,
    DeviceUpdateIn,
    DeviceUpdateOut,
    JoinDeviceIn,
    JoinDeviceOut,
    PairDeviceIn,
    PairDeviceOut,
    PairingScanIn,
    PairingScanOut,
)
from app.schemas.stock import (
    RefillHistory,
    RefillIn,
    RefillModeIn,
    RefillModeOut,
    RefillOut,
    StockOut,
)
from app.services import device_management as svc
from app.services import stock as stock_svc

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/pairing/scan", response_model=PairingScanOut)
async def pairing_scan(body: PairingScanIn, _: CurrentUser, db: DbSession) -> PairingScanOut:
    return await svc.scan(db, body.device_qr_payload)


@router.post("", response_model=PairDeviceOut, status_code=status.HTTP_201_CREATED)
async def pair_device(body: PairDeviceIn, user: CurrentUser, db: DbSession) -> PairDeviceOut:
    return await svc.pair(db, user, body, datetime.now(UTC))


@router.get("", response_model=DeviceList)
async def list_devices(
    user: CurrentUser, db: DbSession, settings: SettingsDep, elderly_id: UUID | None = Query(None)
) -> DeviceList:
    items = await svc.list_devices(db, user, elderly_id, settings)
    return DeviceList(data=items, total=len(items))


@router.post("/{device_id}/join", response_model=JoinDeviceOut)
async def join_device(
    device_id: UUID, body: JoinDeviceIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> JoinDeviceOut:
    return await svc.join(db, user, device_id, body.device_pin, settings, datetime.now(UTC))


@router.put("/{device_id}/pin", response_model=ChangePinOut)
async def change_pin(
    device_id: UUID, body: ChangePinIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> ChangePinOut:
    updated_at = await svc.change_pin(
        db, user, device_id, body.current_device_pin, body.new_device_pin, settings, datetime.now(UTC)
    )
    return ChangePinOut(device_id=device_id, pin_updated_at=updated_at)


@router.get("/{device_id}", response_model=DeviceDetail)
async def device_detail(device_id: UUID, user: CurrentUser, db: DbSession) -> DeviceDetail:
    return await svc.detail(db, user, device_id)


@router.put("/{device_id}", response_model=DeviceUpdateOut)
async def update_device(device_id: UUID, body: DeviceUpdateIn, user: CurrentUser, db: DbSession) -> DeviceUpdateOut:
    return await svc.update_settings(db, user, device_id, body)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unpair_device(device_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    await svc.remove(db, user, device_id, datetime.now(UTC))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
async def device_status(device_id: UUID, user: CurrentUser, db: DbSession, settings: SettingsDep) -> DeviceStatusOut:
    return await svc.status(db, user, device_id, settings)


@router.get("/{device_id}/clock", response_model=ClockOut)
async def device_clock(device_id: UUID, user: CurrentUser, db: DbSession, settings: SettingsDep) -> ClockOut:
    return await svc.clock(db, user, device_id, settings, datetime.now(UTC))


@router.post("/{device_id}/clock/calibrate", response_model=CalibrateOut)
async def calibrate_clock(
    device_id: UUID, body: CalibrateIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> CalibrateOut:
    """Manual time sync: sends `time_sync` over the device WebSocket and waits for the ack."""
    now = datetime.now(UTC)
    device, ack = await svc.calibrate(db, user, device_id, body.device_pin, settings, now)
    clock = await svc.clock(db, user, device.id, settings, datetime.now(UTC))
    return CalibrateOut(
        device_id=device.id,
        device_internal_time=clock.device_internal_time,
        drift_seconds=clock.drift_seconds,
        calibrated_at=ack.acked_at,
        command_id=ack.command_id,
    )


@router.post(
    "/{device_id}/alarm",
    response_model=CommandResultOut,
    responses={
        409: {"description": "DEVICE_OFFLINE or DEVICE_COMMAND_CHANNEL_UNAVAILABLE"},
        502: {"description": "DEVICE_DISCONNECTED or DEVICE_REJECTED_COMMAND"},
        504: {"description": "DEVICE_ACK_TIMEOUT"},
    },
)
async def trigger_alarm(
    device_id: UUID, body: AlarmIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> CommandResultOut:
    """Rings the pillbox (OWNER/ADMIN). Succeeds only after the device acks."""
    return await svc.trigger_alarm(db, user, device_id, body.slot_number, body.duration_seconds, settings)


@router.get("/{device_id}/events", response_model=DeviceEventPage)
async def device_events(device_id: UUID, user: CurrentUser, db: DbSession, pagination: PaginationDep) -> DeviceEventPage:
    """Raw device event log (debugging / audit), newest first."""
    items, total = await svc.list_events(db, user, device_id, pagination.offset, pagination.limit)
    return DeviceEventPage(data=items, page=pagination.page, limit=pagination.limit, total=total)


# --- stock & refill ------------------------------------------------------------

@router.post("/{device_id}/refill-mode", response_model=RefillModeOut)
async def refill_mode(device_id: UUID, body: RefillModeIn, user: CurrentUser, db: DbSession) -> RefillModeOut:
    return await stock_svc.set_refill_mode(db, user, device_id, body.enabled)


@router.post("/{device_id}/refills", response_model=RefillOut, status_code=status.HTTP_201_CREATED)
async def record_refill(
    device_id: UUID, body: RefillIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> RefillOut:
    return await stock_svc.record_refill(db, user, device_id, body, settings, datetime.now(UTC))


@router.get("/{device_id}/refills", response_model=RefillHistory)
async def refill_history(device_id: UUID, user: CurrentUser, db: DbSession, pagination: PaginationDep) -> RefillHistory:
    items, total = await stock_svc.refill_history(db, user, device_id, pagination.offset, pagination.limit)
    return RefillHistory(data=items, page=pagination.page, limit=pagination.limit, total=total)


@router.get("/{device_id}/stock", response_model=list[StockOut])
async def stock(device_id: UUID, user: CurrentUser, db: DbSession, settings: SettingsDep) -> list[StockOut]:
    return await stock_svc.stock_overview(db, user, device_id, settings, datetime.now(UTC))
