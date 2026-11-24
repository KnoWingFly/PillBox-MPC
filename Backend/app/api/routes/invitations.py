"""Invitee side of invitations by code. The inviter side lives under /elderly/{id}/invitations."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.schemas.elderly import InvitationAccepted, InvitationCodeIn, InvitationPreview
from app.services import invitations

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/preview", response_model=InvitationPreview)
async def preview_invitation(
    body: InvitationCodeIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> InvitationPreview:
    return await invitations.preview(db, user, body.code, datetime.now(UTC), settings)


@router.post("/accept", response_model=InvitationAccepted)
async def accept_invitation(
    body: InvitationCodeIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> InvitationAccepted:
    return await invitations.accept(db, user, body.code, datetime.now(UTC), settings)
