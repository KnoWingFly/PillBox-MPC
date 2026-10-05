from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, PaginationDep
from app.schemas.notifications import (
    NotificationDetail,
    NotificationPage,
    ReadAllOut,
    ReadOut,
    ResolveIn,
    ResolveOut,
)
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
