from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser

router = APIRouter(tags=["auth"])


class MeOut(BaseModel):
    id: UUID
    full_name: str
    email: str
    timezone: str


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser) -> MeOut:
    """Sanity check: proves the app's access token is accepted by this backend."""
    return MeOut(id=user.id, full_name=user.full_name, email=user.email, timezone=user.timezone)
