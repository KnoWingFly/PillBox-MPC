from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import MAX_DEVICE_OFFLINE_AFTER_MINUTES, Connectivity, Gender, Role
from app.schemas.common import E164, BirthDate, ElderlyName, FreeText, Label50, Name100


class ElderlyIn(BaseModel):
    full_name: ElderlyName
    nickname: Name100 | None = None
    birth_date: BirthDate | None = None
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


class CaregiverOut(BaseModel):
    caregiver_id: UUID
    full_name: str
    role: Role
    relationship_label: str | None
    added_at: datetime



class CaregiverPage(BaseModel):
    data: list[CaregiverOut]
    page: int
    limit: int
    total: int


class CaregiverRoleIn(BaseModel):
    """PUT /elderly/{id}/caregivers/{caregiver_id}: OWNER changes another caregiver's access."""

    role: Literal["ADMIN", "PEMANTAU"]


# --- invitations by code (services/invitations.py) -----------------------------------

InvitationCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]


class InvitationCreateIn(BaseModel):
    role: Literal["ADMIN", "PEMANTAU"]
    relationship_label: Label50 | None = None


class InvitationCreated(BaseModel):
    """The code is returned once, here only: the server stores its hash."""

    invitation_id: UUID
    code: str
    role: Role
    relationship_label: str | None
    expires_at: datetime


class InvitationOut(BaseModel):
    invitation_id: UUID
    role: Role
    relationship_label: str | None
    # Lets an ADMIN see which pending invitations they may revoke (their own).
    invited_by_user_id: UUID | None
    invited_by_name: str | None
    created_at: datetime
    expires_at: datetime


class InvitationPage(BaseModel):
    data: list[InvitationOut]
    page: int
    limit: int
    total: int


class InvitationCodeIn(BaseModel):
    code: InvitationCode


class InvitationPreview(BaseModel):
    elderly_name: str
    invited_by_name: str | None
    role: Role
    relationship_label: str | None
    expires_at: datetime


class InvitationAccepted(BaseModel):
    elderly_id: UUID
    my_role: Role

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
    notify_on_taken: bool = True  # matches services/notifications.py Preferences
    notify_on_device_offline: bool = True
    device_offline_after_minutes: int = Field(10, ge=1, le=MAX_DEVICE_OFFLINE_AFTER_MINUTES)
    notify_on_low_battery: bool = True
