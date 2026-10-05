from datetime import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.enums import DayPeriod, MealRelation, RowType
from app.schemas.common import HHMM, DaysOfWeek

Tolerance = Literal[15, 30, 45, 60]
_MedName = Field(None, max_length=100)
_Dosage = Field(None, max_length=255)


def _check_window(start: time | None, end: time | None) -> None:
    if start is not None and end is not None and end < start:
        # ASSUMPTION: windows do not cross midnight (matches the DB CHECK).
        raise ValueError("window_end must not be earlier than window_start")


class ScheduleCreateIn(BaseModel):
    slot_number: int = Field(..., ge=1, le=8)
    medication_name: str | None = _MedName
    dosage_info: str | None = _Dosage
    window_start: HHMM
    window_end: HHMM
    tolerance_minutes: Tolerance = 30
    days_of_week: DaysOfWeek = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    active: bool = True

    @model_validator(mode="after")
    def _window(self) -> "ScheduleCreateIn":
        _check_window(self.window_start, self.window_end)
        return self


class ScheduleUpdateIn(BaseModel):
    """Partial update: only fields present in the body change."""

    medication_name: str | None = _MedName
    dosage_info: str | None = _Dosage
    window_start: HHMM | None = None
    window_end: HHMM | None = None
    tolerance_minutes: Tolerance | None = None
    days_of_week: DaysOfWeek | None = None
    active: bool | None = None


class ScheduleOut(BaseModel):
    id: UUID
    device_id: UUID
    slot_number: int
    row: RowType
    meal_relation: MealRelation
    day_period: DayPeriod
    medication_name: str | None
    dosage_info: str | None
    window_start: HHMM
    window_end: HHMM
    tolerance_minutes: int
    days_of_week: list[int]
    active: bool
    config_version: int
    device_notified: bool | None = None


class SlotScheduleOut(BaseModel):
    """GET /schedules returns all 8 slots; empty slots have is_empty=true."""

    id: UUID | None
    slot_number: int
    row: RowType
    meal_relation: MealRelation
    day_period: DayPeriod
    medication_name: str | None
    dosage_info: str | None
    window_start: HHMM | None
    window_end: HHMM | None
    tolerance_minutes: int | None
    days_of_week: list[int]
    active: bool
    is_empty: bool


class ValidateIn(BaseModel):
    slot_number: int = Field(..., ge=1, le=8)
    window_start: HHMM
    window_end: HHMM
    days_of_week: DaysOfWeek = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])

    @model_validator(mode="after")
    def _window(self) -> "ValidateIn":
        _check_window(self.window_start, self.window_end)
        return self


class Conflict(BaseModel):
    type: Literal["WINDOW_OVERLAP"]
    with_slot_number: int
    overlap_from: HHMM
    overlap_to: HHMM


class ValidateOut(BaseModel):
    valid: bool
    conflicts: list[Conflict]
