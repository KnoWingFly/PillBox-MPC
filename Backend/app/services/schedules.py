"""Schedule control for the 8-slot matrix. Every change bumps
devices.config_version (the device pulls GET /config when its applied
version is behind) and pushes a best-effort `schedule_updated` command to a
WebSocket-connected device."""

import logging
from datetime import datetime, time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import conflict, not_found, unprocessable
from app.models import Device, Schedule, User
from app.models.enums import ALL_ROLES, EDITOR_ROLES
from app.schemas.schedules import (
    Conflict,
    ScheduleCreateIn,
    ScheduleOut,
    ScheduleUpdateIn,
    SlotScheduleOut,
    ValidateIn,
    ValidateOut,
)
from app.services.access import get_device_for_user
from app.services.device_management import bump_config, drop_undecided_doses, notify_config_changed
from app.services.slots import all_slots, slot_layout

logger = logging.getLogger(__name__)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _time(minutes: int) -> time:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return time(minutes // 60, minutes % 60)


def find_conflicts(
    window_start: time, window_end: time, days: list[int], others: list[Schedule]
) -> list[Conflict]:
    """Two active slots conflict when they share a weekday and their windows
    overlap (the device can pop up only one chamber at a time). A zero-length
    window (start == end) is treated as one minute."""
    a_start = _minutes(window_start)
    a_end = max(_minutes(window_end), a_start + 1)
    conflicts = []
    for other in others:
        if not other.is_active or not set(days) & set(other.days_of_week):
            continue
        b_start = _minutes(other.window_start)
        b_end = max(_minutes(other.window_end), b_start + 1)
        if a_start < b_end and b_start < a_end:
            conflicts.append(
                Conflict(
                    type="WINDOW_OVERLAP",
                    with_slot_number=other.slot_number,
                    overlap_from=_time(max(a_start, b_start)),
                    overlap_to=_time(min(a_end, b_end)),
                )
            )
    return conflicts


async def _live_schedules(session: AsyncSession, device_id: UUID) -> list[Schedule]:
    rows = await session.execute(
        select(Schedule)
        .where(Schedule.device_id == device_id, Schedule.deleted_at.is_(None))
        .order_by(Schedule.slot_number)
    )
    return list(rows.scalars().all())


def to_out(s: Schedule, config_version: int, device_notified: bool | None = None) -> ScheduleOut:
    layout = slot_layout(s.slot_number)
    return ScheduleOut(
        id=s.id,
        device_id=s.device_id,
        slot_number=s.slot_number,
        row=layout.row,
        meal_relation=layout.meal_relation,
        day_period=layout.day_period,
        medication_name=s.medication_name,
        dosage_info=s.dosage_info,
        window_start=s.window_start,
        window_end=s.window_end,
        tolerance_minutes=s.tolerance_minutes,
        days_of_week=sorted(s.days_of_week),
        active=s.is_active,
        config_version=config_version,
        device_notified=device_notified,
    )


async def list_slots(session: AsyncSession, user: User, device_id: UUID) -> list[SlotScheduleOut]:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    by_slot = {s.slot_number: s for s in await _live_schedules(session, device.id)}
    out = []
    for layout in all_slots():
        s = by_slot.get(layout.slot_number)
        out.append(
            SlotScheduleOut(
                id=s.id if s else None,
                slot_number=layout.slot_number,
                row=layout.row,
                meal_relation=layout.meal_relation,
                day_period=layout.day_period,
                medication_name=s.medication_name if s else None,
                dosage_info=s.dosage_info if s else None,
                window_start=s.window_start if s else None,
                window_end=s.window_end if s else None,
                tolerance_minutes=s.tolerance_minutes if s else None,
                days_of_week=sorted(s.days_of_week) if s else [],
                active=s.is_active if s else False,
                is_empty=s is None,
            )
        )
    return out


def _raise_overlap(conflicts: list[Conflict]) -> None:
    if conflicts:
        raise conflict(
            "WINDOW_OVERLAP",
            "Schedule window overlaps another active slot",
            details=[c.model_dump(mode="json") for c in conflicts],
        )


async def _commit_and_notify(session: AsyncSession, device: Device, schedule: Schedule) -> ScheduleOut:
    version = await bump_config(session, device)
    await session.commit()
    await session.refresh(schedule)
    notified = await notify_config_changed(device.id, version)
    return to_out(schedule, version, notified)


async def create(session: AsyncSession, user: User, device_id: UUID, body: ScheduleCreateIn) -> ScheduleOut:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    live = await _live_schedules(session, device.id)
    if any(s.slot_number == body.slot_number for s in live):
        # ASSUMPTION: POST creates; an occupied slot is edited with PUT.
        raise conflict("SLOT_ALREADY_SCHEDULED", f"Slot {body.slot_number} already has a schedule; use PUT")
    if body.active:
        _raise_overlap(find_conflicts(body.window_start, body.window_end, body.days_of_week, live))
    layout = slot_layout(body.slot_number)
    schedule = Schedule(
        device_id=device.id,
        slot_number=body.slot_number,
        row_type=layout.row.value,
        day_period=layout.day_period.value,
        medication_name=body.medication_name,
        dosage_info=body.dosage_info,
        window_start=body.window_start,
        window_end=body.window_end,
        tolerance_minutes=body.tolerance_minutes,
        days_of_week=body.days_of_week,
        is_active=body.active,
    )
    session.add(schedule)
    await session.flush()
    logger.info("schedule_created", extra={"device_id": str(device.id), "slot": body.slot_number})
    return await _commit_and_notify(session, device, schedule)


async def _get_schedule(session: AsyncSession, device_id: UUID, schedule_id: UUID) -> Schedule:
    schedule = (
        await session.execute(
            select(Schedule)
            .where(Schedule.id == schedule_id, Schedule.device_id == device_id, Schedule.deleted_at.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise not_found(message="Schedule not found")
    return schedule


async def update(
    session: AsyncSession, user: User, device_id: UUID, schedule_id: UUID, body: ScheduleUpdateIn
) -> ScheduleOut:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    schedule = await _get_schedule(session, device.id, schedule_id)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    for required in ("window_start", "window_end", "tolerance_minutes", "days_of_week", "active"):
        if required in changes and changes[required] is None:
            raise unprocessable("VALIDATION_ERROR", f"{required} cannot be null")

    start = changes.get("window_start", schedule.window_start)
    end = changes.get("window_end", schedule.window_end)
    days = changes.get("days_of_week", schedule.days_of_week)
    active = changes.get("active", schedule.is_active)
    if end < start:
        raise unprocessable("VALIDATION_ERROR", "window_end must not be earlier than window_start")
    if active:
        others = [s for s in await _live_schedules(session, device.id) if s.id != schedule.id]
        _raise_overlap(find_conflicts(start, end, days, others))

    timing_changed = any(
        k in changes for k in ("window_start", "window_end", "tolerance_minutes", "days_of_week")
    ) or (active is False and schedule.is_active)
    schedule.window_start = start
    schedule.window_end = end
    schedule.days_of_week = days
    schedule.is_active = active
    if "tolerance_minutes" in changes:
        schedule.tolerance_minutes = changes["tolerance_minutes"]
    if "medication_name" in changes:
        schedule.medication_name = changes["medication_name"]
    if "dosage_info" in changes:
        schedule.dosage_info = changes["dosage_info"]
    if timing_changed:
        # Undecided doses were computed from the old timing; they are re-created
        # from the new timing on the next rules-engine pass if still due.
        await drop_undecided_doses(session, schedule_id=schedule.id)
    logger.info("schedule_updated", extra={"schedule_id": str(schedule.id)})
    return await _commit_and_notify(session, device, schedule)


async def remove(session: AsyncSession, user: User, device_id: UUID, schedule_id: UUID, now: datetime) -> None:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    schedule = await _get_schedule(session, device.id, schedule_id)
    schedule.deleted_at = now  # soft delete keeps dose history linked
    await drop_undecided_doses(session, schedule_id=schedule.id)
    version = await bump_config(session, device)
    await session.commit()
    logger.info("schedule_deleted", extra={"schedule_id": str(schedule.id)})
    await notify_config_changed(device.id, version)


async def validate(session: AsyncSession, user: User, device_id: UUID, body: ValidateIn) -> ValidateOut:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    others = [s for s in await _live_schedules(session, device.id) if s.slot_number != body.slot_number]
    conflicts = find_conflicts(body.window_start, body.window_end, body.days_of_week, others)
    return ValidateOut(valid=not conflicts, conflicts=conflicts)
