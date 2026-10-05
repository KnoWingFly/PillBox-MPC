from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import DayPeriod, JournalStatus, MealRelation


class CalendarDay(BaseModel):
    date: date
    indicator: Literal["FULLY_COMPLIANT", "HAS_LATE", "HAS_MISSED", "NO_SCHEDULE"]
    scheduled: int
    taken_on_time: int
    taken_late: int
    missed: int
    pending: int


class CalendarOut(BaseModel):
    month: str
    compliance_rate: float | None
    avg_delay_minutes: float | None
    days: list[CalendarDay]


class DoseCard(BaseModel):
    dose_log_id: UUID | None  # null for a dose later today that is not due yet
    device_id: UUID
    device_nickname: str | None
    schedule_id: UUID | None
    slot_number: int
    meal_relation: MealRelation
    day_period: DayPeriod
    medication_name: str | None
    scheduled_time: str
    status: JournalStatus
    delay_minutes: int | None
    actual_open_time: datetime | None
    actual_close_time: datetime | None
    chime_count: int | None
    log_source: str | None
    notified_caregiver: str | None
    notified_at: datetime | None


class DayOut(BaseModel):
    date: date
    doses_completed: int
    doses_total: int
    adherence_rate: float | None
    avg_delay_minutes: float | None
    doses: list[DoseCard]


class SummaryOut(BaseModel):
    period: dict[str, date]
    total_scheduled: int
    taken_on_time: int
    taken_late: int
    missed: int
    compliance_rate: float | None
    avg_delay_minutes: float | None


class ManualConfirmationIn(BaseModel):
    override_status: Literal["TAKEN_ON_TIME", "TAKEN_LATE"]
    confirmed_at: datetime
    note: str | None = Field(None, max_length=2000)


class ManualConfirmationOut(BaseModel):
    dose_log_id: UUID
    status: Literal["TAKEN_ON_TIME", "TAKEN_LATE"]
    delay_minutes: int
    log_source: Literal["MANUAL_CAREGIVER_CONFIRMATION"]
    confirmed_by_caregiver_name: str
    note: str | None
