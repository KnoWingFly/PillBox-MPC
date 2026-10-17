from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, PaginationDep, SettingsDep
from app.schemas.journal import ManualConfirmationOut
from app.schemas.notifications import (
    ConfirmTakenIn,
    DeleteAllOut,
    LateReleaseIn,
    LateReleaseOut,
    NotificationDetail,
    NotificationPage,
    ReadAllOut,
    ReadOut,
    ResolveIn,
    ResolveOut,
)
from app.services import late_dose
from app.services import notification_feed as svc
from app.services.notification_feed import Tab

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    user: CurrentUser,
    db: DbSession,
    pagination: PaginationDep,
    tab: Tab = Query("ALL"),
    elderly_id: UUID | None = Query(None),
) -> NotificationPage:
    items, total, unread = await svc.list_feed(db, user, tab, elderly_id, pagination.offset, pagination.limit)
    return NotificationPage(unread_count=unread, data=items, page=pagination.page, limit=pagination.limit, total=total)


@router.put("/read-all", response_model=ReadAllOut)
async def read_all(user: CurrentUser, db: DbSession) -> ReadAllOut:
    return await svc.mark_all_read(db, user)


@router.delete("", response_model=DeleteAllOut)
async def delete_all(
    user: CurrentUser,
    db: DbSession,
    up_to_created_at: datetime = Query(..., description="created_at of the newest notification the user saw"),
    up_to_id: UUID = Query(..., description="its id (tie-break)"),
) -> DeleteAllOut:
    """ "Hapus semua": the caller's notifications at or older than (up_to_created_at, up_to_id)."""
    return DeleteAllOut(deleted=await svc.delete_up_to(db, user, up_to_created_at, up_to_id))


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(notification_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    await svc.delete_one(db, user, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{notification_id}", response_model=NotificationDetail)
async def get_notification(notification_id: UUID, user: CurrentUser, db: DbSession) -> NotificationDetail:
    return await svc.detail(db, user, notification_id)


@router.put("/{notification_id}/read", response_model=ReadOut)
async def read_notification(notification_id: UUID, user: CurrentUser, db: DbSession) -> ReadOut:
    return await svc.mark_read(db, user, notification_id)


@router.put("/{notification_id}/resolve", response_model=ResolveOut)
async def resolve_notification(
    notification_id: UUID, body: ResolveIn, user: CurrentUser, db: DbSession
) -> ResolveOut:
    return await svc.resolve(db, user, notification_id, body.note, datetime.now(UTC))


@router.post(
    "/{notification_id}/late-release",
    response_model=LateReleaseOut,
    responses={
        409: {"description": "LATE_DOSE_TOO_LATE, DOSE_NOT_MISSED, DEVICE_OFFLINE or DEVICE_COMMAND_CHANNEL_UNAVAILABLE"},
        502: {"description": "DEVICE_DISCONNECTED or DEVICE_REJECTED_COMMAND"},
        504: {"description": "DEVICE_ACK_TIMEOUT"},
    },
)
async def late_release(
    notification_id: UUID, body: LateReleaseIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> LateReleaseOut:
    """ "Buka bilik sekarang" for a missed dose (OWNER/ADMIN, device PIN): the pillbox pops the
    chamber up again for LATE_RELEASE_MINUTES; opening it records the dose as taken late."""
    return await late_dose.release(db, user, notification_id, body.device_pin, settings, datetime.now(UTC))


@router.post("/{notification_id}/confirm-taken", response_model=ManualConfirmationOut)
async def confirm_taken(
    notification_id: UUID, body: ConfirmTakenIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> ManualConfirmationOut:
    """ "Sudah diminum" on a missed dose (or a forced open after one): manual TAKEN_LATE."""
    return await late_dose.confirm_taken(db, user, notification_id, body.note, settings, datetime.now(UTC))
