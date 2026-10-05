from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import Connectivity, Gender, Role
from app.schemas.common import E164, FreeText, Label50, Name100


class ElderlyIn(BaseModel):
    full_name: Name100
    nickname: Name100 | None = None
    birth_date: date | None = None
    gender: Gender | None = None
    contact_phone: E164 | None = None
    notes: FreeText | None = None


class ElderlyCreated(BaseModel):
    id: UUID
    full_name: str
    nickname: str | None
    birth_date: date | None
    gender: Gender | None
    contact_phone: str | None
    notes: str | None
    device_count: int
    my_role: Role
    created_at: datetime


class TodaySummary(BaseModel):
    scheduled: int
    taken: int
    missed: int
    pending: int


class ElderlyListItem(BaseModel):
    id: UUID
    full_name: str
    nickname: str | None
    my_role: Role
    device_count: int
    overall_indicator: Literal["GREEN", "YELLOW", "RED", "GRAY"]
    today_summary: TodaySummary
    open_alert_count: int


class ElderlyPage(BaseModel):
    data: list[ElderlyListItem]
    page: int
    limit: int
    total: int


class ElderlyDeviceBrief(BaseModel):
    id: UUID
    device_nickname: str | None
    connectivity: Connectivity


class ElderlyDetail(BaseModel):
    id: UUID
    full_name: str
    nickname: str | None
    birth_date: date | None
    gender: Gender | None
    contact_phone: str | None
    notes: str | None
    my_role: Role
    devices: list[ElderlyDeviceBrief]
    caregiver_count: int
    updated_at: datetime


class CaregiverInvite(BaseModel):
    email: EmailStr
    role: Literal["ADMIN", "PEMANTAU"]
    relationship_label: Label50 | None = None


class CaregiverOut(BaseModel):
    caregiver_id: UUID
    full_name: str
    role: Role
    relationship_label: str | None
    added_at: datetime


class TransferOwnershipIn(BaseModel):
    new_owner_caregiver_id: UUID


class TransferOwnershipOut(BaseModel):
    message: Literal["OWNERSHIP_TRANSFERRED"]
    your_new_role: Role


class Channels(BaseModel):
    push: bool = True
    whatsapp: bool = False


class NotificationPreferencesIO(BaseModel):
    channels: Channels = Field(default_factory=Channels)
    whatsapp_number: str | None = None
    notify_on_missed: bool = True
    notify_on_taken: bool = False
    notify_on_device_offline: bool = True
    device_offline_after_minutes: int = Field(10, ge=1, le=1440)
    notify_on_low_battery: bool = True
