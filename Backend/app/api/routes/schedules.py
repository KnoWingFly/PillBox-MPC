from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.schemas.schedules import (
    ScheduleCreateIn,
    ScheduleOut,
    ScheduleUpdateIn,
    SlotScheduleOut,
    SlotsWriteIn,
    ValidateIn,
    ValidateOut,
)
from app.services import schedules as svc

router = APIRouter(prefix="/devices/{device_id}/schedules", tags=["schedules"])


@router.get("", response_model=list[SlotScheduleOut])
async def list_schedules(device_id: UUID, user: CurrentUser, db: DbSession) -> list[SlotScheduleOut]:
    """All 8 slots; empty slots have is_empty=true."""
    return await svc.list_slots(db, user, device_id)


@router.put("", response_model=list[SlotScheduleOut])
async def save_schedules(
    device_id: UUID, body: SlotsWriteIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> list[SlotScheduleOut]:
    """Saves several slots at once (the app's "Simpan ke Pillbox"); returns all 8 slots.
    409 WINDOW_OVERLAP / SCHEDULE_TOO_CLOSE / SLOT_IN_PROGRESS: nothing is saved."""
    return await svc.save_slots(db, user, device_id, body, datetime.now(UTC), settings)


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_schedule(device_id: UUID, body: ScheduleCreateIn, user: CurrentUser, db: DbSession) -> ScheduleOut:
    return await svc.create(db, user, device_id, body)


# Registered before /{schedule_id} so "validate" is never parsed as an id.
@router.post("/validate", response_model=ValidateOut)
async def validate_schedule(device_id: UUID, body: ValidateIn, user: CurrentUser, db: DbSession) -> ValidateOut:
    return await svc.validate(db, user, device_id, body)


@router.put("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    device_id: UUID, schedule_id: UUID, body: ScheduleUpdateIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> ScheduleOut:
    return await svc.update(db, user, device_id, schedule_id, body, datetime.now(UTC), settings)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    device_id: UUID, schedule_id: UUID, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> Response:
    await svc.remove(db, user, device_id, schedule_id, datetime.now(UTC), settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
