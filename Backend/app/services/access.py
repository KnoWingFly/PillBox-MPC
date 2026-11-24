"""Elderly-level authorization via user_elderly_roles.

OWNER / ADMIN may change things (schedules, alarms, device settings);
PEMANTAU is read-only. A caller with no role on the elderly gets 404 (not
403) so resource existence is not leaked.
"""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import conflict, forbidden, not_found
from app.models import Device, Elderly, UserElderlyRole
from app.models.enums import Role


async def get_role(session: AsyncSession, user_id: UUID, elderly_id: UUID) -> Role | None:
    row = await session.execute(
        select(UserElderlyRole.role)
        .join(Elderly, Elderly.id == UserElderlyRole.elderly_id)
        .where(
            UserElderlyRole.user_id == user_id,
            UserElderlyRole.elderly_id == elderly_id,
            Elderly.deleted_at.is_(None),
        )
    )
    role = row.scalar_one_or_none()
    return Role(role) if role else None


def _deny(allowed: Collection[Role]) -> Exception:
    if set(allowed) == {Role.OWNER}:
        return forbidden("OWNER_ONLY", "Only the owner can do this")
    return forbidden()


async def require_role(
    session: AsyncSession, user_id: UUID, elderly_id: UUID, allowed: Collection[Role]
) -> Role:
    role = await get_role(session, user_id, elderly_id)
    if role is None:
        raise not_found(message="Elderly not found")
    if role not in allowed:
        raise _deny(allowed)
    return role


# Roles a caregiver may hand out, by the giver's own role (docs/ai/domain.md): an ADMIN
# invites monitors only, so the ADMIN role is granted only by the OWNER.
GRANTABLE_ROLES: dict[Role, frozenset[Role]] = {
    Role.OWNER: frozenset({Role.ADMIN, Role.PEMANTAU}),
    Role.ADMIN: frozenset({Role.PEMANTAU}),
    Role.PEMANTAU: frozenset(),
}


def require_grantable(giver: Role, role: Role) -> None:
    if role not in GRANTABLE_ROLES[giver]:
        raise forbidden(message="Your role cannot grant this access")


async def ensure_member_room(session: AsyncSession, elderly_id: UUID, settings: Settings) -> None:
    """409 MEMBER_LIMIT_REACHED when one more caregiver would exceed MAX_CAREGIVERS_PER_ELDERLY.
    Locks the elderly row until the caller commits, so two joins at once cannot both pass the count."""
    await session.execute(select(Elderly.id).where(Elderly.id == elderly_id).with_for_update())
    members = await session.scalar(
        select(func.count()).select_from(UserElderlyRole).where(UserElderlyRole.elderly_id == elderly_id)
    )
    if (members or 0) >= settings.max_caregivers_per_elderly:
        raise conflict("MEMBER_LIMIT_REACHED", "This elderly profile already has the maximum number of caregivers")


async def get_device_for_user(
    session: AsyncSession,
    user_id: UUID,
    device_id: UUID,
    allowed: Collection[Role],
    *,
    for_update: bool = False,
) -> tuple[Device, Role]:
    # Device and the caller's role in one query (every device route runs this first; each query
    # is one or two round trips to the remote database).
    stmt = (
        select(Device, UserElderlyRole.role, Elderly.id)
        .outerjoin(
            UserElderlyRole,
            and_(UserElderlyRole.elderly_id == Device.elderly_id, UserElderlyRole.user_id == user_id),
        )
        .outerjoin(Elderly, and_(Elderly.id == Device.elderly_id, Elderly.deleted_at.is_(None)))
        .where(Device.id == device_id)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Device, key_share=True)  # see device_protocol.find_device
    row = (await session.execute(stmt)).one_or_none()
    if row is None or row[0].elderly_id is None or row[1] is None or row[2] is None:
        raise not_found(message="Device not found")
    device, role = row[0], Role(row[1])
    if role not in allowed:
        raise _deny(allowed)
    return device, role
