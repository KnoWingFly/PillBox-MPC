from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import NotificationType, Severity


class NotificationItem(BaseModel):
    id: UUID
    type: NotificationType
    severity: Severity
    elderly_id: UUID | None
    elderly_nickname: str | None
    device_id: UUID | None
    device_nickname: str | None
    slot_number: int | None
    delay_minutes: int | None
    message: str
    is_read: bool
    is_resolved: bool
    created_at: datetime


class NotificationPage(BaseModel):
    unread_count: int
    data: list[NotificationItem]
    page: int
    limit: int
    total: int


class NotificationDetail(NotificationItem):
    related_dose_log_id: UUID | None
    resolved_by_caregiver_name: str | None
    resolved_at: datetime | None
    resolution_note: str | None


class ResolveIn(BaseModel):
    note: str | None = Field(None, max_length=2000)


class ResolveOut(BaseModel):
    id: UUID
    is_resolved: bool
    resolved_at: datetime
    resolved_by_caregiver_name: str
    note: str | None


class ReadOut(BaseModel):
    id: UUID
    is_read: bool


class ReadAllOut(BaseModel):
    marked_read: int
