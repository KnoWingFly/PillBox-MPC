"""Caregiver notification center: list/filter, detail, read, resolve, delete."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Select, delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import conflict, not_found
from app.models import Device, Elderly, Notification, TelemetryLog, User
from app.models.enums import DoseStatus, NotificationType, Severity
from app.schemas.notifications import (
    NotificationDetail,
    NotificationItem,
    ReadAllOut,
    ReadOut,
    ResolveOut,
)
from app.services.late_dose import CONFIRM_TAKEN, LATE_RELEASE

Tab = Literal["ALL", "LATE_MISSED", "RESOLVED"]
_LATE_MISSED = [NotificationType.DOSE_LATE.value, NotificationType.DOSE_MISSED.value]


def _base() -> Select[Any]:
    return (
        select(
            Notification,
            Elderly.nickname,
            Elderly.full_name,
            Device.device_nickname,
            TelemetryLog.slot_number,
            TelemetryLog.delay_minutes,
            TelemetryLog.status,
        )
        .outerjoin(Elderly, Elderly.id == Notification.elderly_id)
        .outerjoin(Device, Device.id == Notification.device_id)
        .outerjoin(TelemetryLog, TelemetryLog.id == Notification.telemetry_log_id)
    )


def _item(
    n: Notification,
    nickname: str | None,
    full_name: str | None,
    device: str | None,
    slot: int | None,
    delay: int | None,
    dose_status: str | None,
) -> NotificationItem:
    return NotificationItem(
        id=n.id,
        type=NotificationType(n.type),
        severity=Severity(n.severity),
        elderly_id=n.elderly_id,
        elderly_nickname=nickname or full_name,
        device_id=n.device_id,
        device_nickname=device,
        slot_number=slot,
        delay_minutes=delay,
        message=n.message,
        is_read=n.is_read,
        is_resolved=n.is_resolved,
        created_at=n.created_at,
        actions=actions_for(n, dose_status),
    )


def actions_for(n: Notification, dose_status: str | None) -> list[str]:
    """See services/late_dose.py. The cutoff is checked when the action is used."""
    if n.is_resolved or dose_status != DoseStatus.MISSED:
        return []
    if n.type == NotificationType.DOSE_MISSED:
        return [LATE_RELEASE, CONFIRM_TAKEN]
    if n.type == NotificationType.UNSCHEDULED_OPEN:
        return [CONFIRM_TAKEN]  # forced open linked to a missed dose
    return []


async def list_feed(
    session: AsyncSession, user: User, tab: Tab, elderly_id: UUID | None, offset: int, limit: int
) -> tuple[list[NotificationItem], int, int]:
    conditions = [Notification.user_id == user.id]
    if elderly_id is not None:
        conditions.append(Notification.elderly_id == elderly_id)
    if tab == "LATE_MISSED":
        # ASSUMPTION: the "Terlambat & Terlewat" tab shows open (unresolved) incidents.
        conditions += [Notification.type.in_(_LATE_MISSED), Notification.is_resolved.is_(False)]
    elif tab == "RESOLVED":
        conditions.append(Notification.is_resolved.is_(True))
    # Both counts in one round trip (the app polls this endpoint), as separate scalar subqueries
    # so each can use its own index (unread: index-only on notifications_user_unread_idx) instead
    # of one filtered aggregate reading every notification row the user ever had.
    total_q = select(func.count()).select_from(Notification).where(*conditions).scalar_subquery()
    unread_q = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .scalar_subquery()
    )
    # The counts ride along as two extra columns of the page query: one round trip per poll.
    rows = (
        await session.execute(
            # id breaks ties like the app's feed order (Mobile/lib/feed.ts compareFeed).
            _base()
            .add_columns(total_q, unread_q)
            .where(*conditions)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if rows:
        total, unread = rows[0][-2], rows[0][-1]
    else:  # empty page (nothing yet, or past the end): the counts on their own
        total, unread = (await session.execute(select(total_q, unread_q))).one()
    return [_item(*row[:-2]) for row in rows], total, unread


async def _own(session: AsyncSession, user: User, notification_id: UUID) -> Notification:
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise not_found(message="Notification not found")
    return n


async def detail(session: AsyncSession, user: User, notification_id: UUID) -> NotificationDetail:
    resolver = aliased(User)
    row = (
        await session.execute(
            _base()
            .add_columns(resolver.full_name)
            .outerjoin(resolver, resolver.id == Notification.resolved_by_user_id)
            .where(Notification.id == notification_id, Notification.user_id == user.id)
        )
    ).first()
    if row is None:
        raise not_found(message="Notification not found")
    n, nickname, full_name, device, slot, delay, dose_status, resolver_name = row
    item = _item(n, nickname, full_name, device, slot, delay, dose_status)
    return NotificationDetail(
        **item.model_dump(),
        related_dose_log_id=n.telemetry_log_id,
        resolved_by_caregiver_name=resolver_name,
        resolved_at=n.resolved_at,
        resolution_note=n.resolution_note,
    )


async def mark_read(session: AsyncSession, user: User, notification_id: UUID) -> ReadOut:
    n = await _own(session, user, notification_id)
    n.is_read = True
    await session.commit()
    return ReadOut(id=n.id, is_read=True)


async def mark_all_read(session: AsyncSession, user: User) -> ReadAllOut:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
        .returning(Notification.id)
    )
    count = len(result.all())
    await session.commit()
    return ReadAllOut(marked_read=count)


async def resolve(session: AsyncSession, user: User, notification_id: UUID, note: str | None, now: datetime) -> ResolveOut:
    n = await _own(session, user, notification_id)
    if n.is_resolved:
        raise conflict("ALREADY_RESOLVED", "This notification is already resolved")
    values = {"is_resolved": True, "resolved_by_user_id": user.id, "resolved_at": now, "resolution_note": note}
    if n.event_key:
        # The incident is shared: resolving it resolves every caregiver's copy.
        await session.execute(
            update(Notification)
            .where(Notification.event_key == n.event_key, Notification.is_resolved.is_(False))
            .values(**values)
        )
    else:
        await session.execute(update(Notification).where(Notification.id == n.id).values(**values))
    await session.commit()
    return ResolveOut(
        id=n.id, is_resolved=True, resolved_at=now, resolved_by_caregiver_name=user.full_name, note=note
    )


async def delete_one(session: AsyncSession, user: User, notification_id: UUID) -> None:
    """Deletes the caller's own copy only; other caregivers keep theirs of a shared incident."""
    result = await session.execute(
        delete(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .returning(Notification.id)
    )
    if result.first() is None:
        raise not_found(message="Notification not found")
    await session.commit()


async def delete_up_to(
    session: AsyncSession, user: User, boundary: tuple[datetime, UUID] | None, device_id: UUID | None
) -> int:
    """ "Hapus semua": deletes the caller's notifications at or older than the newest one they saw
    when confirming (boundary), so anything that arrived afterwards survives; with device_id only
    that pillbox's (another caregiver's copies are never touched; an unknown or foreign device just
    matches nothing). Feed order is (created_at, id) descending; created_at is compared to the
    millisecond because that is what the app holds."""
    conditions = [Notification.user_id == user.id]
    if boundary is not None:
        created_ms = func.date_trunc("milliseconds", Notification.created_at)
        conditions.append(tuple_(created_ms, Notification.id) <= tuple_(*boundary))
    if device_id is not None:
        conditions.append(Notification.device_id == device_id)
    result = await session.execute(delete(Notification).where(*conditions))
    deleted = result.rowcount or 0
    await session.commit()
    return deleted
