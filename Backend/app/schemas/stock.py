from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RefillModeIn(BaseModel):
    enabled: bool


class RefillModeOut(BaseModel):
    device_id: UUID
    is_refill_mode: bool
    device_notified: bool


class RefillItemIO(BaseModel):
    slot_number: int  # range checked in the service -> 422 SLOT_NOT_FOUND
    unit_dose_count: int


class RefillIn(BaseModel):
    refilled_at: datetime | None = None
    is_reset: bool = False
    items: list[RefillItemIO] = Field(..., min_length=1, max_length=8)


class StockAfter(BaseModel):
    slot_number: int
    remaining_units: int


class RefillOut(BaseModel):
    id: UUID
    refilled_at: datetime
    is_reset: bool
    items: list[RefillItemIO]
    stock_after: list[StockAfter]


class RefillHistoryItem(BaseModel):
    id: UUID
    refilled_at: datetime
    is_reset: bool
    refilled_by_caregiver_name: str | None
    items: list[RefillItemIO]


class RefillHistory(BaseModel):
    data: list[RefillHistoryItem]
    page: int
    limit: int
    total: int


class StockOut(BaseModel):
    slot_number: int
    remaining_units: int
    estimated_empty_date: date | None
    low_stock: bool
    updated_at: datetime | None
