from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, PaginationDep
from app.schemas.elderly import (
    CaregiverInvite,
    CaregiverOut,
    ElderlyCreated,
    ElderlyDetail,
    ElderlyIn,
    ElderlyPage,
    NotificationPreferencesIO,
    TransferOwnershipIn,
    TransferOwnershipOut,
)
from app.schemas.journal import CalendarOut, DayOut, SummaryOut
from app.services import elderly as svc
from app.services import journal

router = APIRouter(prefix="/elderly", tags=["elderly"])


@router.post("", response_model=ElderlyCreated, status_code=status.HTTP_201_CREATED)
async def create_elderly(body: ElderlyIn, user: CurrentUser, db: DbSession) -> ElderlyCreated:
    return await svc.create(db, user, body, datetime.now(UTC))


@router.get("", response_model=ElderlyPage)
async def list_elderly(user: CurrentUser, db: DbSession, pagination: PaginationDep) -> ElderlyPage:
    items, total = await svc.list_for_user(db, user, pagination.offset, pagination.limit, datetime.now(UTC))
    return ElderlyPage(data=items, page=pagination.page, limit=pagination.limit, total=total)


@router.get("/{elderly_id}", response_model=ElderlyDetail)
async def get_elderly(elderly_id: UUID, user: CurrentUser, db: DbSession) -> ElderlyDetail:
    return await svc.detail(db, user, elderly_id)


@router.put("/{elderly_id}", response_model=ElderlyDetail)
async def update_elderly(elderly_id: UUID, body: ElderlyIn, user: CurrentUser, db: DbSession) -> ElderlyDetail:
    return await svc.update(db, user, elderly_id, body)


@router.delete("/{elderly_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_elderly(elderly_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    await svc.soft_delete(db, user, elderly_id, datetime.now(UTC))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- caregivers ------------------------------------------------------------------

@router.post("/{elderly_id}/caregivers", response_model=CaregiverOut, status_code=status.HTTP_201_CREATED)
async def invite_caregiver(elderly_id: UUID, body: CaregiverInvite, user: CurrentUser, db: DbSession) -> CaregiverOut:
    return await svc.invite(db, user, elderly_id, body, datetime.now(UTC))


@router.get("/{elderly_id}/caregivers", response_model=list[CaregiverOut])
async def list_caregivers(elderly_id: UUID, user: CurrentUser, db: DbSession) -> list[CaregiverOut]:
    return await svc.list_caregivers(db, user, elderly_id)


@router.delete("/{elderly_id}/caregivers/{caregiver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_caregiver(elderly_id: UUID, caregiver_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    await svc.remove_caregiver(db, user, elderly_id, caregiver_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{elderly_id}/transfer-ownership", response_model=TransferOwnershipOut)
async def transfer_ownership(
    elderly_id: UUID, body: TransferOwnershipIn, user: CurrentUser, db: DbSession
) -> TransferOwnershipOut:
    return await svc.transfer_ownership(db, user, elderly_id, body.new_owner_caregiver_id)


# --- notification preferences ------------------------------------------------------

@router.get("/{elderly_id}/notification-preferences", response_model=NotificationPreferencesIO)
async def get_preferences(elderly_id: UUID, user: CurrentUser, db: DbSession) -> NotificationPreferencesIO:
    return await svc.get_preferences(db, user, elderly_id)


@router.put("/{elderly_id}/notification-preferences", response_model=NotificationPreferencesIO)
async def put_preferences(
    elderly_id: UUID, body: NotificationPreferencesIO, user: CurrentUser, db: DbSession
) -> NotificationPreferencesIO:
    return await svc.put_preferences(db, user, elderly_id, body, datetime.now(UTC))


# --- journal (registered calendar/summary before /{date}) ---------------------------

@router.get("/{elderly_id}/journal/calendar", response_model=CalendarOut)
async def journal_calendar(
    elderly_id: UUID, user: CurrentUser, db: DbSession, month: str = Query(..., pattern=r"^\d{4}-\d{2}$")
) -> CalendarOut:
    return await journal.calendar_view(db, user, elderly_id, month, datetime.now(UTC))


@router.get("/{elderly_id}/journal/summary", response_model=SummaryOut)
async def journal_summary(
    elderly_id: UUID, user: CurrentUser, db: DbSession, start: date = Query(...), end: date = Query(...)
) -> SummaryOut:
    return await journal.summary_view(db, user, elderly_id, start, end)


@router.get("/{elderly_id}/journal/{day}", response_model=DayOut)
async def journal_day(elderly_id: UUID, day: date, user: CurrentUser, db: DbSession) -> DayOut:
    """Daily timeline. `day` is YYYY-MM-DD (local date of the doses)."""
    return await journal.day_view(db, user, elderly_id, day, datetime.now(UTC))
