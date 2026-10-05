"""The 8-slot matrix. Row A (slots 1-4) = before meal, row B (slots 5-8) =
after meal; columns = morning, afternoon, evening, night. Matches the
emulator (SmartDevice/smart_pillbox/db/database.py _DEFAULT_SCHEDULE) and the
mobile app's A1..A4 / B1..B4 slot ids."""

from dataclasses import dataclass

from app.models.enums import DayPeriod, MealRelation, RowType

SLOT_NUMBERS = range(1, 9)
_PERIODS = (DayPeriod.MORNING, DayPeriod.AFTERNOON, DayPeriod.EVENING, DayPeriod.NIGHT)


@dataclass(frozen=True)
class SlotLayout:
    slot_number: int
    row: RowType
    meal_relation: MealRelation
    day_period: DayPeriod


def slot_layout(slot_number: int) -> SlotLayout:
    if slot_number not in SLOT_NUMBERS:
        raise ValueError(f"slot_number must be 1-8, got {slot_number}")
    before = slot_number <= 4
    return SlotLayout(
        slot_number=slot_number,
        row=RowType.A if before else RowType.B,
        meal_relation=MealRelation.BEFORE_MEAL if before else MealRelation.AFTER_MEAL,
        day_period=_PERIODS[(slot_number - 1) % 4],
    )


def all_slots() -> list[SlotLayout]:
    return [slot_layout(n) for n in SLOT_NUMBERS]
