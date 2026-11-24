"""Caregiver invitations by one-time code (docs/ROLES_FEATURE_PLAN.md, phase R2).

An OWNER or ADMIN creates a PENDING invitation for a role and shares its code (e.g. on WhatsApp).
The invitee previews it and accepts it, so nobody joins an elderly profile without consent and no
email address is needed, which also means the endpoint never reveals who has an account.

Codes: 8 characters from an alphabet without look-alikes (no 0/O, 1/I/L), shown as XXXX-XXXX,
about 40 bits. Only their SHA-256 is stored. Previews and accepts are rate-limited per user
(INVITE_CODE), and every unusable code (unknown, expired, used, revoked, or for a deleted elderly)
answers the same 404 INVITATION_INVALID. A code also dies when its inviter can no longer grant its
role (demoted, removed, left, or account deleted): it is neither listed nor accepted.
"""

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import conflict, not_found
from app.models import Elderly, Invitation, User, UserElderlyRole
from app.models.enums import EDITOR_ROLES, AttemptScope, InvitationStatus, Role
from app.schemas.elderly import (
    InvitationAccepted,
    InvitationCreated,
    InvitationCreateIn,
    InvitationOut,
    InvitationPreview,
)
from app.services import pin_attempts
from app.services.access import GRANTABLE_ROLES, ensure_member_room, get_role, require_grantable, require_role
from app.services.app_hub import queue_roles_changed
from app.services.elderly import count_invite_attempt

logger = logging.getLogger(__name__)

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
_CODE_GROUP = CODE_LENGTH // 2
_NOT_CODE_CHARS = re.compile(r"[^0-9A-Z]")


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:_CODE_GROUP]}-{raw[_CODE_GROUP:]}"


def normalize_code(code: str) -> str | None:
    """Uppercase, without separators or spaces. None when it cannot be a code."""
    raw = _NOT_CODE_CHARS.sub("", code.upper())
    if len(raw) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in raw):
        return None
    return raw


def hash_code(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def _invalid() -> Exception:
    return not_found("INVITATION_INVALID", "This invitation code is not valid")


def _elderly_name(elderly: Elderly) -> str:
    return elderly.nickname or elderly.full_name


# --- inviter side -----------------------------------------------------------------------

async def create(
    session: AsyncSession, user: User, elderly_id: UUID, body: InvitationCreateIn, now: datetime, settings: Settings
) -> InvitationCreated:
    my_role = await require_role(session, user.id, elderly_id, EDITOR_ROLES)
    role = Role(body.role)
    require_grantable(my_role, role)
    await count_invite_attempt(session, user, settings)
    await ensure_member_room(session, elderly_id, settings)
    expires_at = now + timedelta(days=settings.invitation_ttl_days)
    # A collision of two random 40-bit codes is negligible; the unique index guards it anyway.
    code = new_code()
    invitation = Invitation(
        elderly_id=elderly_id,
        invited_by_user_id=user.id,
        role=role.value,
        relationship_label=body.relationship_label,
        status=InvitationStatus.PENDING.value,
        code_hash=hash_code(normalize_code(code) or ""),
        expires_at=expires_at,
        created_at=now,
    )
    session.add(invitation)
    await session.commit()
    logger.info("invitation_created", extra={"elderly_id": str(elderly_id), "role": role.value})
    return InvitationCreated(
        invitation_id=invitation.id,
        code=code,
        role=role,
        relationship_label=body.relationship_label,
        expires_at=expires_at,
    )


# The inviter is still a caregiver of the elderly with a role that may grant the invitation's role.
_INVITER_ROLE = and_(
    UserElderlyRole.user_id == Invitation.invited_by_user_id,
    UserElderlyRole.elderly_id == Invitation.elderly_id,
)
_INVITER_MAY_GRANT = or_(
    *(
        and_(UserElderlyRole.role == giver.value, Invitation.role.in_([r.value for r in roles]))
        for giver, roles in GRANTABLE_ROLES.items()
        if roles
    )
)


def _pending(elderly_id: UUID, now: datetime):  # noqa: ANN202 (SQLAlchemy select)
    return (
        select(Invitation)
        .join(UserElderlyRole, _INVITER_ROLE)
        .where(
            Invitation.elderly_id == elderly_id,
            Invitation.status == InvitationStatus.PENDING.value,
            Invitation.code_hash.is_not(None),
            Invitation.expires_at > now,
            _INVITER_MAY_GRANT,
        )
    )


async def list_pending(
    session: AsyncSession, user: User, elderly_id: UUID, now: datetime, offset: int, limit: int
) -> tuple[list[InvitationOut], int]:
    await require_role(session, user.id, elderly_id, EDITOR_ROLES)
    base = _pending(elderly_id, now).subquery()
    rows = (
        await session.execute(
            select(base, User.full_name, func.count().over().label("total"))
            .outerjoin(User, User.id == base.c.invited_by_user_id)
            .order_by(base.c.created_at.desc(), base.c.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if rows:
        total = rows[0].total
    elif offset == 0:
        total = 0
    else:  # a page past the end: count separately
        total = int(await session.scalar(select(func.count()).select_from(base)) or 0)
    return [
        InvitationOut(
            invitation_id=r.id,
            role=Role(r.role),
            relationship_label=r.relationship_label,
            invited_by_user_id=r.invited_by_user_id,
            invited_by_name=r.full_name,
            created_at=r.created_at,
            expires_at=r.expires_at,
        )
        for r in rows
    ], total


async def revoke(session: AsyncSession, user: User, elderly_id: UUID, invitation_id: UUID, now: datetime) -> None:
    """OWNER revokes any pending invitation; an ADMIN only the ones they created."""
    my_role = await require_role(session, user.id, elderly_id, EDITOR_ROLES)
    invitation = (
        await session.execute(
            _pending(elderly_id, now).where(Invitation.id == invitation_id).with_for_update(of=Invitation)
        )
    ).scalar_one_or_none()
    if invitation is None or (my_role != Role.OWNER and invitation.invited_by_user_id != user.id):
        raise not_found("INVITATION_NOT_FOUND", "Invitation not found")
    invitation.status = InvitationStatus.REVOKED.value
    invitation.responded_at = now
    await session.commit()


# --- invitee side -----------------------------------------------------------------------

async def _count_code_attempt(session: AsyncSession, user: User, settings: Settings) -> None:
    await session.commit()  # the counter uses its own short transaction and connection
    await pin_attempts.register_attempt(
        AttemptScope.INVITE_CODE,
        str(user.id),
        settings.invitation_code_max_attempts,
        settings.invitation_code_window_seconds,
        "Too many invitation codes tried, try again later",
    )


async def _usable(session: AsyncSession, code: str, now: datetime, *, lock: bool) -> tuple[Invitation, Elderly]:
    normalized = normalize_code(code)
    if normalized is None:
        raise _invalid()
    stmt = (
        select(Invitation, Elderly)
        .join(Elderly, Elderly.id == Invitation.elderly_id)
        .join(UserElderlyRole, _INVITER_ROLE)
        .where(
            Invitation.code_hash == hash_code(normalized),
            Invitation.status == InvitationStatus.PENDING.value,
            Invitation.expires_at > now,
            Elderly.deleted_at.is_(None),
            _INVITER_MAY_GRANT,
        )
    )
    if lock:
        stmt = stmt.with_for_update(of=Invitation)
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise _invalid()
    return row[0], row[1]


async def preview(session: AsyncSession, user: User, code: str, now: datetime, settings: Settings) -> InvitationPreview:
    await _count_code_attempt(session, user, settings)
    invitation, elderly = await _usable(session, code, now, lock=False)
    if await get_role(session, user.id, elderly.id) is not None:
        raise conflict("ALREADY_CAREGIVER", "You are already a caregiver of this elderly")
    inviter = await session.get(User, invitation.invited_by_user_id) if invitation.invited_by_user_id else None
    return InvitationPreview(
        elderly_name=_elderly_name(elderly),
        invited_by_name=inviter.full_name if inviter else None,
        role=Role(invitation.role),
        relationship_label=invitation.relationship_label,
        expires_at=invitation.expires_at,
    )


async def accept(session: AsyncSession, user: User, code: str, now: datetime, settings: Settings) -> InvitationAccepted:
    await _count_code_attempt(session, user, settings)
    # Locked: two people using the same code at once cannot both get in.
    invitation, elderly = await _usable(session, code, now, lock=True)
    if await get_role(session, user.id, elderly.id) is not None:
        raise conflict("ALREADY_CAREGIVER", "You are already a caregiver of this elderly")
    await ensure_member_room(session, elderly.id, settings)
    role = Role(invitation.role)
    session.add(
        UserElderlyRole(
            user_id=user.id,
            elderly_id=elderly.id,
            role=role.value,
            relationship_label=invitation.relationship_label,
            created_at=now,
        )
    )
    invitation.status = InvitationStatus.ACCEPTED.value
    invitation.invitee_user_id = user.id
    invitation.responded_at = now
    # The invitee starts following this elderly; the inviter's app refreshes its member list.
    recipients = [user.id] + ([invitation.invited_by_user_id] if invitation.invited_by_user_id else [])
    queue_roles_changed(session, *recipients)
    try:
        await session.commit()
    except IntegrityError as exc:
        # The same user accepted another invitation for this elderly at the same moment.
        await session.rollback()
        raise conflict("ALREADY_CAREGIVER", "You are already a caregiver of this elderly") from exc
    logger.info("invitation_accepted", extra={"elderly_id": str(elderly.id), "role": role.value})
    return InvitationAccepted(elderly_id=elderly.id, my_role=role)
