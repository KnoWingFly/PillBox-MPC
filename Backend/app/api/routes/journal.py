from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.journal import ManualConfirmationIn, ManualConfirmationOut
from app.services import journal

router = APIRouter(prefix="/journal", tags=["journal"])


@router.put("/dose-logs/{dose_log_id}/manual-confirmation", response_model=ManualConfirmationOut)
async def manual_confirmation(
    dose_log_id: UUID, body: ManualConfirmationIn, user: CurrentUser, db: DbSession
) -> ManualConfirmationOut:
    return await journal.manual_confirmation(db, user, dose_log_id, body, datetime.now(UTC))
