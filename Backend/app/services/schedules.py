"""Schedule control for the 8-slot matrix. Every change bumps
devices.config_version (the device pulls GET /config when its applied
version is behind) and pushes a best-effort `schedule_updated` command to a
WebSocket-connected device."""

import logging
from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import conflict, not_found, unprocessable
from app.models import Device, Schedule, TelemetryLog, User
from app.models.enums import ALL_ROLES, EDITOR_ROLES, DoseStatus
from app.schemas.schedules import (
    Conflict,
    ScheduleCreateIn,
    ScheduleOut,
    ScheduleUpdateIn,
    SlotScheduleOut,
    SlotsWriteIn,
    ValidateIn,
    ValidateOut,
)
from app.services.access import get_device_for_user
from app.services.adherence import dose_instants, is_scheduled_on
from app.services.device_clock import device_now
from app.services.device_management import bump_config, drop_undecided_doses, notify_config_changed
from app.services.doses import slot_label
from app.services.slots import all_slots, slot_layout
from app.services.timeutil import zone

logger = logging.getLogger(__name__)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _time(minutes: int) -> time:
    minutes %= _DAY
    return time(minutes // 60, minutes % 60)


_DAY = 24 * 60
_WEEK = 7 * _DAY


def _week_ranges(start: time, end: time, extra: int, days: list[int]) -> list[tuple[int, int]]:
    """[from, to) minutes on a Monday-based week for each scheduled day: the window plus `extra`
    (the tolerance) at its end. Something zero-length (start == end, no extra) counts as one minute,
    so 08:00 + 30 min tolerance is [08:00, 08:30) and a slot at 08:30 fits right after it."""
    length = max(_minutes(end) - _minutes(start) + extra, 1)
    return [((d - 1) * _DAY + _minutes(start), (d - 1) * _DAY + _minutes(start) + length) for d in days]


def _overlap(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> tuple[int, int] | None:
    """First overlap of two week range lists, wrapping Sunday night into Monday morning."""
    for a_from, a_to in a:
        for b_from, b_to in b:
            for shift in (-_WEEK, 0, _WEEK):
                lo, hi = max(a_from, b_from + shift), min(a_to, b_to + shift)
                if lo < hi:
                    return lo, hi
    return None


def find_conflicts(
    window_start: time,
    window_end: time,
    days: list[int],
    others: list[Schedule],
    tolerance_minutes: int = 0,
    slot_number: int | None = None,
) -> list[Conflict]:
    """Two active slots conflict when their windows overlap on a shared weekday (WINDOW_OVERLAP),
    or when one slot's dose window (window + tolerance, the time it may stay popped up) reaches
    into the other's (TOO_CLOSE): the device pops up only one chamber at a time, so the later one
    would queue and could be missed. Windows running past midnight are checked against the next
    day."""
    mine = _week_ranges(window_start, window_end, 0, days)
    mine_dose = _week_ranges(window_start, window_end, tolerance_minutes, days)
    conflicts = []
    for other in others:
        if not other.is_active:
            continue
        theirs = _week_ranges(other.window_start, other.window_end, 0, other.days_of_week)
        hit = _overlap(mine, theirs)
        if hit is not None:
            conflicts.append(
                Conflict(
                    type="WINDOW_OVERLAP", slot_number=slot_number, with_slot_number=other.slot_number,
                    overlap_from=_time(hit[0]), overlap_to=_time(hit[1]),
                )
            )
            continue
        theirs_dose = _week_ranges(other.window_start, other.window_end, other.tolerance_minutes, other.days_of_week)
        hit = _overlap(mine_dose, theirs_dose)
        if hit is not None:
            # The overlap begins where the later slot starts; the earlier slot is the one that has
            # been running longer at that point. It needs its window + tolerance before the next.
            mine_first = (hit[0] - _minutes(window_start)) % _DAY > (hit[0] - _minutes(other.window_start)) % _DAY
            first_start, first_end, first_tol = (
                (window_start, window_end, tolerance_minutes) if mine_first
                else (other.window_start, other.window_end, other.tolerance_minutes)
            )
            conflicts.append(
                Conflict(
                    type="TOO_CLOSE", slot_number=slot_number, with_slot_number=other.slot_number,
                    overlap_from=_time(hit[0]), overlap_to=_time(hit[1]),
                    required_gap_minutes=_minutes(first_end) - _minutes(first_start) + first_tol,
                )
            )
    return conflicts


async def ensure_not_in_progress(
    session: AsyncSession, device: Device, schedule: Schedule, now: datetime, settings: Settings
) -> None:
    """Refuses a change to a slot's timing, on/off state or existence while its dose is under way
    on the pillbox: the door is open, the dose window is open and not decided yet (the chamber is
    popped up or about to be), or a missed dose was re-opened ("Buka bilik sekarang"). Changing it
    then would drop the pending dose, so the take that follows would be lost or land on the wrong
    time. Medication name / dosage edits are always allowed."""
    label = slot_label(schedule.slot_number)
    doors = {int(c["slot_number"]): c["door"] for c in (device.chamber_doors or [])}
    if doors.get(schedule.slot_number) == "OPEN":
        raise conflict(
            "SLOT_IN_PROGRESS", f"Pintu bilik {label} sedang terbuka di pillbox. Tutup dulu, lalu simpan lagi."
        )
    tz = zone(device.timezone)
    clock = device_now(device, now, settings)
    today = clock.astimezone(tz).date()
    rows = await session.execute(
        select(TelemetryLog.scheduled_for, TelemetryLog.status, TelemetryLog.late_release_until).where(
            TelemetryLog.schedule_id == schedule.id,
            TelemetryLog.scheduled_date >= today - timedelta(days=1),
            TelemetryLog.status.is_not(None),
        )
    )
    decided: dict[datetime, str] = {}
    for scheduled_for, status, released_until in rows.all():
        if status == DoseStatus.MISSED and released_until is not None and released_until > clock:
            raise conflict(
                "SLOT_IN_PROGRESS",
                f"Bilik {label} sedang dibuka lagi untuk dosis yang terlewat (sampai "
                f"{released_until.astimezone(tz):%H:%M}). Ubah setelah itu selesai.",
            )
        if status in (DoseStatus.TAKEN, DoseStatus.MISSED):
            decided[scheduled_for] = status
    for day in (today, today - timedelta(days=1)):
        if not is_scheduled_on(schedule.days_of_week, day):
            continue
        inst = dose_instants(day, schedule.window_start, schedule.window_end, schedule.tolerance_minutes, tz)
        if inst.scheduled_for <= clock < inst.deadline_at and inst.scheduled_for not in decided:
            raise conflict(
                "SLOT_IN_PROGRESS",
                f"Slot {label} sedang berbunyi di pillbox (jadwal {inst.scheduled_for.astimezone(tz):%H:%M}, "
                f"sampai {inst.deadline_at.astimezone(tz):%H:%M}). Ubah setelah obatnya diambil atau waktunya lewat.",
            )


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
    return _slot_outs({s.slot_number: s for s in await _live_schedules(session, device.id)})


def _slot_outs(by_slot: dict[int, Schedule]) -> list[SlotScheduleOut]:
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
    if not conflicts:
        return
    first = conflicts[0]
    other = slot_label(first.with_slot_number)
    me = f"Slot {slot_label(first.slot_number)}" if first.slot_number else "Jadwal ini"
    if first.type == "WINDOW_OVERLAP":
        code = "WINDOW_OVERLAP"
        message = f"{me} bentrok dengan slot {other} pada {first.overlap_from:%H:%M}. Pilih jam lain."
    else:
        code = "SCHEDULE_TOO_CLOSE"
        message = (
            f"{me} terlalu dekat dengan slot {other}: pillbox hanya membuka satu bilik sekaligus, "
            f"jadi beri jarak minimal {first.required_gap_minutes} menit (selama waktu toleransinya)."
        )
    raise conflict(code, message, details=[c.model_dump(mode="json") for c in conflicts])


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
        _raise_overlap(
            find_conflicts(
                body.window_start, body.window_end, body.days_of_week, live, body.tolerance_minutes, body.slot_number
            )
        )
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
    session: AsyncSession,
    user: User,
    device_id: UUID,
    schedule_id: UUID,
    body: ScheduleUpdateIn,
    now: datetime,
    settings: Settings,
) -> ScheduleOut:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    schedule = await _get_schedule(session, device.id, schedule_id)
    changes = body.model_dump(exclude_unset=True)
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
        tolerance = changes.get("tolerance_minutes", schedule.tolerance_minutes)
        _raise_overlap(find_conflicts(start, end, days, others, tolerance, schedule.slot_number))

    timing_changed = any(
        k in changes for k in ("window_start", "window_end", "tolerance_minutes", "days_of_week")
    ) or (active is False and schedule.is_active)
    if timing_changed:
        await ensure_not_in_progress(session, device, schedule, now, settings)
    if timing_changed or (active and not schedule.is_active):
        schedule.effective_from = now  # doses at the new timing count from now on (rules engine)
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


async def remove(
    session: AsyncSession, user: User, device_id: UUID, schedule_id: UUID, now: datetime, settings: Settings
) -> None:
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    schedule = await _get_schedule(session, device.id, schedule_id)
    await ensure_not_in_progress(session, device, schedule, now, settings)
    schedule.deleted_at = now  # soft delete keeps dose history linked
    await drop_undecided_doses(session, schedule_id=schedule.id)
    version = await bump_config(session, device)
    await session.commit()
    logger.info("schedule_deleted", extra={"schedule_id": str(schedule.id)})
    await notify_config_changed(device.id, version)


async def validate(session: AsyncSession, user: User, device_id: UUID, body: ValidateIn) -> ValidateOut:
    device, _ = await get_device_for_user(session, user.id, device_id, ALL_ROLES)
    others = [s for s in await _live_schedules(session, device.id) if s.slot_number != body.slot_number]
    conflicts = find_conflicts(
        body.window_start, body.window_end, body.days_of_week, others, body.tolerance_minutes, body.slot_number
    )
    return ValidateOut(valid=not conflicts, conflicts=conflicts)


_TIMING_FIELDS = ("window_start", "window_end", "tolerance_minutes", "days_of_week")


async def save_slots(
    session: AsyncSession, user: User, device_id: UUID, body: SlotsWriteIn, now: datetime, settings: Settings
) -> list[SlotScheduleOut]:
    """Saves several slots in one transaction: one device lock, one config version and one
    `schedule_updated` push, instead of one of each per slot (every round trip to a remote
    database is expensive). Overlaps are checked on the final state, so the order of the
    slots does not matter. All or nothing."""
    device, _ = await get_device_for_user(session, user.id, device_id, EDITOR_ROLES, for_update=True)
    live = {s.slot_number: s for s in await _live_schedules(session, device.id)}
    changed = False
    for item in body.slots:
        current = live.get(item.slot_number)
        if item.clear:
            if current is not None:
                await ensure_not_in_progress(session, device, current, now, settings)
                current.deleted_at = now  # soft delete keeps dose history linked
                await drop_undecided_doses(session, schedule_id=current.id)
                del live[item.slot_number]
                changed = True
            continue
        # Attributes, not model_dump(): HHMM serializes times back to "HH:MM" strings.
        fields = {k: getattr(item, k) for k in item.model_fields_set - {"slot_number", "clear"}}
        for required in ("window_start", "window_end", "tolerance_minutes", "days_of_week", "active"):
            if required in fields and fields[required] is None:
                raise unprocessable("VALIDATION_ERROR", f"slot {item.slot_number}: {required} cannot be null")
        if current is None:
            if item.window_start is None or item.window_end is None:
                raise unprocessable("VALIDATION_ERROR", f"slot {item.slot_number}: window_start and window_end are required")
            layout = slot_layout(item.slot_number)
            schedule = Schedule(
                device_id=device.id,
                slot_number=item.slot_number,
                row_type=layout.row.value,
                day_period=layout.day_period.value,
                medication_name=item.medication_name,
                dosage_info=item.dosage_info,
                window_start=item.window_start,
                window_end=item.window_end,
                tolerance_minutes=item.tolerance_minutes or 30,
                days_of_week=item.days_of_week or [1, 2, 3, 4, 5, 6, 7],
                is_active=True if item.active is None else item.active,
                effective_from=now,
            )
            session.add(schedule)
            live[item.slot_number] = schedule
            changed = True
            continue
        updates = {("is_active" if k == "active" else k): v for k, v in fields.items()}
        updates = {k: v for k, v in updates.items() if getattr(current, k) != v}
        if not updates:
            continue
        timing_changed = any(k in updates for k in _TIMING_FIELDS) or updates.get("is_active") is False
        if timing_changed:
            await ensure_not_in_progress(session, device, current, now, settings)
        if timing_changed or updates.get("is_active") is True:
            current.effective_from = now  # doses at the new timing count from now on (rules engine)
        for key, value in updates.items():
            setattr(current, key, value)
        if current.window_end < current.window_start:
            raise unprocessable("VALIDATION_ERROR", f"slot {item.slot_number}: window_end must not be earlier than window_start")
        if timing_changed:
            await drop_undecided_doses(session, schedule_id=current.id)
        changed = True

    active = [s for s in live.values() if s.is_active]
    # Slots this request touches first, so the message names the slot the caregiver just edited.
    touched = {item.slot_number for item in body.slots}
    for s in sorted(active, key=lambda s: s.slot_number not in touched):
        others = [o for o in active if o is not s]
        _raise_overlap(find_conflicts(s.window_start, s.window_end, s.days_of_week, others, s.tolerance_minutes, s.slot_number))

    if not changed:
        await session.commit()  # releases the device lock (a rollback would expire the rows read)
        return _slot_outs(live)
    await session.flush()
    version = await bump_config(session, device)
    await session.commit()
    logger.info("schedules_saved", extra={"device_id": str(device.id), "slots": [s.slot_number for s in body.slots]})
    await notify_config_changed(device.id, version)
    return _slot_outs(live)
