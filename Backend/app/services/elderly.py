"""Elderly profiles, caregivers (roles + invitations), ownership transfer,
and per-caregiver notification preferences."""

import logging
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, conflict, not_found, unprocessable
from app.models import Device, Elderly, Invitation, Notification, NotificationPreference, User, UserElderlyRole
from app.models.enums import ALL_ROLES, EDITOR_ROLES, Connectivity, Gender, InvitationStatus, Role, Severity
from app.schemas.elderly import (
    CaregiverInvite,
    CaregiverOut,
    Channels,
    ElderlyCreated,
    ElderlyDetail,
    ElderlyDeviceBrief,
    ElderlyIn,
    ElderlyListItem,
    NotificationPreferencesIO,
    TodaySummary,
    TransferOwnershipOut,
)
from app.services.access import require_role
from app.services.device_management import unpair
from app.services.journal import day_doses, summarize
from app.services.timeutil import zone

logger = logging.getLogger(__name__)

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


async def create(session: AsyncSession, user: User, body: ElderlyIn, now: datetime) -> ElderlyCreated:
    elderly = Elderly(
        full_name=body.full_name,
        nickname=body.nickname,
        birth_date=body.birth_date,
        gender=body.gender.value if body.gender else None,
        contact_phone=body.contact_phone,
        notes=body.notes,
        created_by_user_id=user.id,
    )
    session.add(elderly)
    await session.flush()
    session.add(UserElderlyRole(user_id=user.id, elderly_id=elderly.id, role=Role.OWNER.value, created_at=now))
    await session.commit()
    await session.refresh(elderly)
    logger.info("elderly_created", extra={"elderly_id": str(elderly.id), "user_id": str(user.id)})
    return ElderlyCreated(
        id=elderly.id,
        full_name=elderly.full_name,
        nickname=elderly.nickname,
        birth_date=elderly.birth_date,
        gender=Gender(elderly.gender) if elderly.gender else None,
        contact_phone=elderly.contact_phone,
        notes=elderly.notes,
        device_count=0,
        my_role=Role.OWNER,
        created_at=elderly.created_at,
    )


Overall = Literal["GREEN", "YELLOW", "RED", "GRAY"]


def _overall(summary_missed: int, summary_late: int, scheduled: int) -> Overall:
    if scheduled == 0:
        return "GRAY"
    if summary_missed:
        return "RED"
    if summary_late:
        return "YELLOW"
    return "GREEN"


async def list_for_user(
    session: AsyncSession, user: User, offset: int, limit: int, now: datetime
) -> tuple[list[ElderlyListItem], int]:
    base = (
        select(Elderly, UserElderlyRole.role)
        .join(UserElderlyRole, UserElderlyRole.elderly_id == Elderly.id)
        .where(UserElderlyRole.user_id == user.id, Elderly.deleted_at.is_(None))
    )
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(Elderly.created_at).offset(offset).limit(limit))).all()
    items = []
    for elderly, role in rows:
        devices = list(
            (await session.execute(select(Device).where(Device.elderly_id == elderly.id))).scalars().all()
        )
        # "Today" is each device's own local date.
        today_for = {d.id: now.astimezone(zone(d.timezone)).date() for d in devices}
        summary = summarize(await day_doses(session, elderly.id, devices, today_for, now))
        open_alerts = (
            await session.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.user_id == user.id,
                    Notification.elderly_id == elderly.id,
                    Notification.is_resolved.is_(False),
                    Notification.severity.in_([Severity.WARNING.value, Severity.CRITICAL.value]),
                )
            )
        ).scalar_one()
        items.append(
            ElderlyListItem(
                id=elderly.id,
                full_name=elderly.full_name,
                nickname=elderly.nickname,
                my_role=Role(role),
                device_count=len(devices),
                overall_indicator=_overall(summary.missed, summary.taken_late, summary.scheduled),
                today_summary=TodaySummary(
                    scheduled=summary.scheduled, taken=summary.taken, missed=summary.missed, pending=summary.pending
                ),
                open_alert_count=open_alerts,
            )
        )
    return items, total


async def detail(session: AsyncSession, user: User, elderly_id: UUID) -> ElderlyDetail:
    role = await require_role(session, user.id, elderly_id, ALL_ROLES)
    elderly = await session.get(Elderly, elderly_id)
    if elderly is None:
        raise not_found(message="Elderly not found")
    devices = (await session.execute(select(Device).where(Device.elderly_id == elderly_id))).scalars().all()
    caregivers = (
        await session.execute(
            select(func.count()).select_from(UserElderlyRole).where(UserElderlyRole.elderly_id == elderly_id)
        )
    ).scalar_one()
    return ElderlyDetail(
        id=elderly.id,
        full_name=elderly.full_name,
        nickname=elderly.nickname,
        birth_date=elderly.birth_date,
        gender=Gender(elderly.gender) if elderly.gender else None,
        contact_phone=elderly.contact_phone,
        notes=elderly.notes,
        my_role=role,
        devices=[
            ElderlyDeviceBrief(id=d.id, device_nickname=d.device_nickname, connectivity=Connectivity(d.status))
            for d in devices
        ],
        caregiver_count=caregivers,
        updated_at=elderly.updated_at,
    )


async def update(session: AsyncSession, user: User, elderly_id: UUID, body: ElderlyIn) -> ElderlyDetail:
    await require_role(session, user.id, elderly_id, EDITOR_ROLES)
    elderly = await session.get(Elderly, elderly_id, with_for_update=True)
    if elderly is None:
        raise not_found(message="Elderly not found")
    # API List: same body as POST, i.e. a full replacement of the profile.
    elderly.full_name = body.full_name
    elderly.nickname = body.nickname
    elderly.birth_date = body.birth_date
    elderly.gender = body.gender.value if body.gender else None
    elderly.contact_phone = body.contact_phone
    elderly.notes = body.notes
    await session.commit()
    return await detail(session, user, elderly_id)


async def soft_delete(session: AsyncSession, user: User, elderly_id: UUID, now: datetime) -> None:
    await require_role(session, user.id, elderly_id, {Role.OWNER})
    elderly = await session.get(Elderly, elderly_id, with_for_update=True)
    if elderly is None:
        raise not_found(message="Elderly not found")
    devices = (
        await session.execute(select(Device).where(Device.elderly_id == elderly_id).with_for_update())
    ).scalars().all()
    for device in devices:
        await unpair(session, device, now)
    elderly.deleted_at = now
    await session.commit()
    logger.info("elderly_deleted", extra={"elderly_id": str(elderly_id), "devices_unpaired": len(devices)})


# --- caregivers -------------------------------------------------------------------

async def invite(
    session: AsyncSession, user: User, elderly_id: UUID, body: CaregiverInvite, now: datetime
) -> CaregiverOut:
    await require_role(session, user.id, elderly_id, EDITOR_ROLES)
    email = body.email.strip().lower()  # Mobile stores emails lowercase
    if email == user.email.lower():
        raise AppError(400, "CANNOT_INVITE_SELF", "You cannot invite yourself")
    invitee = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if invitee is None:
        raise not_found("CAREGIVER_NOT_REGISTERED", "No PillCare account uses this email")
    existing = (
        await session.execute(
            select(UserElderlyRole).where(
                UserElderlyRole.user_id == invitee.id, UserElderlyRole.elderly_id == elderly_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise conflict("ALREADY_CAREGIVER", "This user is already a caregiver of this elderly")
    # The API List adds a registered user immediately; the invitation row is
    # kept as the audit record (status ACCEPTED). ASSUMPTION.
    session.add(
        Invitation(
            elderly_id=elderly_id,
            invited_by_user_id=user.id,
            invitee_email=email,
            invitee_user_id=invitee.id,
            role=body.role,
            relationship_label=body.relationship_label,
            status=InvitationStatus.ACCEPTED.value,
            responded_at=now,
        )
    )
    session.add(
        UserElderlyRole(
            user_id=invitee.id,
            elderly_id=elderly_id,
            role=body.role,
            relationship_label=body.relationship_label,
            created_at=now,
        )
    )
    await session.commit()
    logger.info("caregiver_added", extra={"elderly_id": str(elderly_id), "caregiver_id": str(invitee.id)})
    return CaregiverOut(
        caregiver_id=invitee.id,
        full_name=invitee.full_name,
        role=Role(body.role),
        relationship_label=body.relationship_label,
        added_at=now,
    )


async def list_caregivers(session: AsyncSession, user: User, elderly_id: UUID) -> list[CaregiverOut]:
    await require_role(session, user.id, elderly_id, ALL_ROLES)
    rows = await session.execute(
        select(UserElderlyRole, User.full_name)
        .join(User, User.id == UserElderlyRole.user_id)
        .where(UserElderlyRole.elderly_id == elderly_id)
        .order_by(UserElderlyRole.created_at)
    )
    return [
        CaregiverOut(
            caregiver_id=r.user_id, full_name=name, role=Role(r.role),
            relationship_label=r.relationship_label, added_at=r.created_at,
        )
        for r, name in rows.all()
    ]


async def remove_caregiver(session: AsyncSession, user: User, elderly_id: UUID, caregiver_id: UUID) -> None:
    my_role = await require_role(session, user.id, elderly_id, ALL_ROLES)
    target = (
        await session.execute(
            select(UserElderlyRole).where(
                UserElderlyRole.user_id == caregiver_id, UserElderlyRole.elderly_id == elderly_id
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise not_found("CAREGIVER_NOT_FOUND", "Caregiver not found")
    if target.role == Role.OWNER:
        raise conflict("CANNOT_REMOVE_OWNER", "Transfer ownership before removing the owner")
    if my_role != Role.OWNER and caregiver_id != user.id:
        raise AppError(403, "FORBIDDEN", "Only the owner can remove other caregivers")
    await session.delete(target)
    await session.execute(
        delete(NotificationPreference).where(
            NotificationPreference.user_id == caregiver_id, NotificationPreference.elderly_id == elderly_id
        )
    )
    await session.commit()


async def transfer_ownership(
    session: AsyncSession, user: User, elderly_id: UUID, new_owner_id: UUID
) -> TransferOwnershipOut:
    await require_role(session, user.id, elderly_id, {Role.OWNER})
    roles = {
        r.user_id: r
        for r in (
            await session.execute(
                select(UserElderlyRole).where(UserElderlyRole.elderly_id == elderly_id).with_for_update()
            )
        ).scalars()
    }
    target = roles.get(new_owner_id)
    if target is None or new_owner_id == user.id:
        raise not_found("CAREGIVER_NOT_FOUND", "The new owner must be another caregiver of this elderly")
    mine = roles[user.id]
    # Demote first: the partial unique index allows only one OWNER at a time.
    mine.role = Role.ADMIN.value
    await session.flush()
    target.role = Role.OWNER.value
    await session.commit()
    logger.info("ownership_transferred", extra={"elderly_id": str(elderly_id), "new_owner": str(new_owner_id)})
    return TransferOwnershipOut(message="OWNERSHIP_TRANSFERRED", your_new_role=Role.ADMIN)


# --- notification preferences -------------------------------------------------------

def _prefs_out(row: NotificationPreference | None) -> NotificationPreferencesIO:
    if row is None:
        return NotificationPreferencesIO()
    return NotificationPreferencesIO(
        channels=Channels(push=row.push_enabled, whatsapp=row.whatsapp_enabled),
        whatsapp_number=row.whatsapp_number,
        notify_on_missed=row.notify_on_missed,
        notify_on_taken=row.notify_on_taken,
        notify_on_device_offline=row.notify_on_device_offline,
        device_offline_after_minutes=row.device_offline_after_minutes,
        notify_on_low_battery=row.notify_on_low_battery,
    )


async def _prefs_row(session: AsyncSession, user_id: UUID, elderly_id: UUID) -> NotificationPreference | None:
    return (
        await session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id, NotificationPreference.elderly_id == elderly_id
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def get_preferences(session: AsyncSession, user: User, elderly_id: UUID) -> NotificationPreferencesIO:
    await require_role(session, user.id, elderly_id, ALL_ROLES)
    return _prefs_out(await _prefs_row(session, user.id, elderly_id))


async def put_preferences(
    session: AsyncSession, user: User, elderly_id: UUID, body: NotificationPreferencesIO, now: datetime
) -> NotificationPreferencesIO:
    await require_role(session, user.id, elderly_id, ALL_ROLES)
    if not body.notify_on_missed:
        raise unprocessable("MISSED_NOTIFICATION_CANNOT_BE_DISABLED", "Missed-dose notifications cannot be disabled")
    number = body.whatsapp_number.strip() if body.whatsapp_number else None
    if (number is not None and not _E164.match(number)) or (body.channels.whatsapp and number is None):
        raise unprocessable("INVALID_WHATSAPP_NUMBER", "WhatsApp number must be in E.164 format, e.g. +6281234567890")
    values = {
        "push_enabled": body.channels.push,
        "whatsapp_enabled": body.channels.whatsapp,
        "whatsapp_number": number,
        "notify_on_missed": True,
        "notify_on_taken": body.notify_on_taken,
        "notify_on_device_offline": body.notify_on_device_offline,
        "device_offline_after_minutes": body.device_offline_after_minutes,
        "notify_on_low_battery": body.notify_on_low_battery,
    }
    await session.execute(
        insert(NotificationPreference)
        .values(user_id=user.id, elderly_id=elderly_id, **values)
        .on_conflict_do_update(
            index_elements=[NotificationPreference.user_id, NotificationPreference.elderly_id],
            set_={**values, "updated_at": now},
        )
    )
    await session.commit()
    return _prefs_out(await _prefs_row(session, user.id, elderly_id))
