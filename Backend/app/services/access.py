"""Elderly-level authorization via user_elderly_roles.

OWNER / ADMIN may change things (schedules, alarms, device settings);
PEMANTAU is read-only. A caller with no role on the elderly gets 404 (not
403) so resource existence is not leaked.
"""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import forbidden, not_found
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


async def get_device_for_user(
    session: AsyncSession,
    user_id: UUID,
    device_id: UUID,
    allowed: Collection[Role],
    *,
    for_update: bool = False,
) -> tuple[Device, Role]:
    stmt = select(Device).where(Device.id == device_id)
    if for_update:
        stmt = stmt.with_for_update()
    device = (await session.execute(stmt)).scalar_one_or_none()
    if device is None or device.elderly_id is None:
        raise not_found(message="Device not found")
    role = await get_role(session, user_id, device.elderly_id)
    if role is None:
        raise not_found(message="Device not found")
    if role not in allowed:
        raise _deny(allowed)
    return device, role
