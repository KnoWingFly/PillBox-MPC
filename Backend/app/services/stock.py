"""Stock and refills.

Source of truth: the device holds the physical sachets and reports
stock_count per chamber in every heartbeat, which overwrites device_stocks.
App refills (POST /refills) record who refilled what and update
device_stocks immediately, so the app is correct before the next heartbeat.
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import unprocessable
from app.models import DeviceStock, Refill, RefillItem, Schedule, User
from app.models.enums import ALL_ROLES, EDITOR_ROLES
from app.schemas.stock import (
    RefillHistoryItem,
    RefillIn,
    RefillItemIO,
    RefillModeOut,
    RefillOut,
    StockAfter,
    StockOut,
)
from app.services.access import get_device_for_user
from app.services.connection_manager import DeviceCommand, connection_manager
from app.services.device_management import bump_config
from app.services.slots import SLOT_NUMBERS
from app.services.timeutil import as_aware, zone

logger = logging.getLogger(__name__)


async def set_refill_mode(session: AsyncSession, user: User, device_id: UUID, enabled: bool) -> RefillModeOut:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    if device.is_refill_mode != enabled:
        device.is_refill_mode = enabled
        # Included in GET /config, so REST-only devices learn it on next pull.
        await bump_config(session, device)
    await session.commit()
    notified = await connection_manager.notify(device.id, DeviceCommand.REFILL_MODE, {"enabled": enabled})
    return RefillModeOut(device_id=device.id, is_refill_mode=enabled, device_notified=notified)


def _validate_items(body: RefillIn, capacity: int) -> None:
    slots = [i.slot_number for i in body.items]
    bad_slots = [s for s in slots if s not in SLOT_NUMBERS]
    if bad_slots:
        raise unprocessable("SLOT_NOT_FOUND", "slot_number must be 1-8", details={"slot_numbers": bad_slots})
    if len(set(slots)) != len(slots):
        raise unprocessable("VALIDATION_ERROR", "Each slot may appear only once per refill")
    minimum = 0 if body.is_reset else 1
    bad = [i.slot_number for i in body.items if not minimum <= i.unit_dose_count <= capacity]
    if bad:
        raise unprocessable(
            "UNIT_DOSE_COUNT_OUT_OF_RANGE",
            f"unit_dose_count must be {minimum}-{capacity}",
            details={"slot_numbers": bad},
        )


async def record_refill(
    session: AsyncSession, user: User, device_id: UUID, body: RefillIn, settings: Settings, now: datetime
) -> RefillOut:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    capacity = settings.stock_capacity_per_slot
    _validate_items(body, capacity)

    current_rows = await session.execute(
        select(DeviceStock).where(DeviceStock.device_id == device.id).with_for_update()
    )
    current = {row.slot_number: row.remaining_units for row in current_rows.scalars().all()}
    new_values: dict[int, int] = {}
    overflow = []
    for item in body.items:
        value = item.unit_dose_count if body.is_reset else current.get(item.slot_number, 0) + item.unit_dose_count
        if value > capacity:
            overflow.append(item.slot_number)
        new_values[item.slot_number] = value
    if overflow:
        raise unprocessable(
            "UNIT_DOSE_COUNT_OUT_OF_RANGE",
            f"Refill would exceed the {capacity}-unit capacity",
            details={"slot_numbers": overflow},
        )

    refilled_at = as_aware(body.refilled_at, zone(device.timezone)) if body.refilled_at else now
    refill = Refill(device_id=device.id, refilled_by_user_id=user.id, refilled_at=refilled_at, is_reset=body.is_reset)
    session.add(refill)
    await session.flush()
    session.add_all(
        RefillItem(refill_id=refill.id, slot_number=i.slot_number, unit_dose_count=i.unit_dose_count)
        for i in body.items
    )
    for slot, value in new_values.items():
        await session.execute(
            insert(DeviceStock)
            .values(device_id=device.id, slot_number=slot, remaining_units=value)
            .on_conflict_do_update(
                index_elements=[DeviceStock.device_id, DeviceStock.slot_number],
                set_={"remaining_units": value, "updated_at": now},
            )
        )
    was_refill_mode = device.is_refill_mode
    device.is_refill_mode = False  # API List: recording a refill ends refill mode
    if was_refill_mode:
        await bump_config(session, device)
    await session.commit()
    if was_refill_mode:
        await connection_manager.notify(device.id, DeviceCommand.REFILL_MODE, {"enabled": False})

    after = {**current, **new_values}
    return RefillOut(
        id=refill.id,
        refilled_at=refilled_at,
        is_reset=body.is_reset,
        items=[RefillItemIO(slot_number=i.slot_number, unit_dose_count=i.unit_dose_count) for i in body.items],
        stock_after=[StockAfter(slot_number=n, remaining_units=after.get(n, 0)) for n in SLOT_NUMBERS],
    )


async def refill_history(
    session: AsyncSession, user: User, device_id: UUID, offset: int, limit: int
) -> tuple[list[RefillHistoryItem], int]:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    total = (
        await session.execute(select(func.count()).select_from(Refill).where(Refill.device_id == device.id))
    ).scalar_one()
    rows = await session.execute(
        select(Refill, User.full_name)
        .outerjoin(User, User.id == Refill.refilled_by_user_id)
        .where(Refill.device_id == device.id)
        .order_by(Refill.refilled_at.desc())
        .offset(offset)
        .limit(limit)
    )
    refills = rows.all()
    items_by_refill: dict[UUID, list[RefillItemIO]] = {r.id: [] for r, _ in refills}
    if items_by_refill:
        item_rows = await session.execute(
            select(RefillItem).where(RefillItem.refill_id.in_(list(items_by_refill))).order_by(RefillItem.slot_number)
        )
        for item in item_rows.scalars().all():
            items_by_refill[item.refill_id].append(
                RefillItemIO(slot_number=item.slot_number, unit_dose_count=item.unit_dose_count)
            )
    return [
        RefillHistoryItem(
            id=r.id, refilled_at=r.refilled_at, is_reset=r.is_reset,
            refilled_by_caregiver_name=name, items=items_by_refill[r.id],
        )
        for r, name in refills
    ], total


async def stock_overview(
    session: AsyncSession, user: User, device_id: UUID, settings: Settings, now: datetime
) -> list[StockOut]:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    stocks = {
        s.slot_number: s
        for s in (await session.execute(select(DeviceStock).where(DeviceStock.device_id == device.id))).scalars()
    }
    schedules = await session.execute(
        select(Schedule).where(
            Schedule.device_id == device.id, Schedule.deleted_at.is_(None), Schedule.is_active.is_(True)
        )
    )
    # One unit per scheduled day: doses/day = scheduled weekdays / 7.
    daily_rate = {s.slot_number: len(set(s.days_of_week)) / 7.0 for s in schedules.scalars().all()}
    today = now.astimezone(zone(device.timezone)).date()
    out = []
    for slot in SLOT_NUMBERS:
        row = stocks.get(slot)
        remaining = row.remaining_units if row else 0
        rate = daily_rate.get(slot, 0.0)
        out.append(
            StockOut(
                slot_number=slot,
                remaining_units=remaining,
                # ASSUMPTION: linear estimate from the active schedule's weekdays.
                estimated_empty_date=today + timedelta(days=int(remaining / rate)) if rate > 0 else None,
                low_stock=rate > 0 and remaining <= settings.low_stock_threshold_units,
                updated_at=row.updated_at if row else None,
            )
        )
    return out
