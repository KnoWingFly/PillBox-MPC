from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ChimeVolume, Connectivity, DayPeriod, MealRelation, Role, RowType
from app.schemas.common import Name100, TimeZoneName


class PairingScanIn(BaseModel):
    device_qr_payload: str = Field(..., min_length=1, max_length=512)


class PairingScanOut(BaseModel):
    device_id: UUID
    is_registered: bool
    elderly_name_if_owned: str | None


class SlotLayoutOut(BaseModel):
    slot_number: int
    row: RowType
    meal_relation: MealRelation
    day_period: DayPeriod


class PairDeviceIn(BaseModel):
    device_qr_payload: str = Field(..., min_length=1, max_length=512)
    elderly_id: UUID
    device_nickname: Name100
    timezone: TimeZoneName | None = None  # defaults to the caller's users.timezone
    device_pin: str  # validated in the service -> 422 DEVICE_PIN_INVALID


class PairDeviceOut(BaseModel):
    id: UUID
    device_nickname: str | None
    elderly_id: UUID
    connectivity: Connectivity
    config_version: int
    paired_at: datetime
    slots: list[SlotLayoutOut]


class JoinDeviceIn(BaseModel):
    device_pin: str


class JoinDeviceOut(BaseModel):
    device_id: UUID
    elderly_id: UUID
    my_role: Role
    joined_at: datetime


class ChangePinIn(BaseModel):
    current_device_pin: str
    new_device_pin: str


class ChangePinOut(BaseModel):
    device_id: UUID
    pin_updated_at: datetime


class DeviceListItem(BaseModel):
    id: UUID
    device_code: str
    device_nickname: str | None
    elderly_id: UUID
    elderly_nickname: str | None
    connectivity: Connectivity
    battery_percent: int | None
    estimated_battery_days_remaining: float | None
    last_seen_at: datetime | None


class DeviceList(BaseModel):
    data: list[DeviceListItem]
    total: int


class DeviceSlotOut(BaseModel):
    slot_number: int
    row: RowType
    meal_relation: MealRelation
    day_period: DayPeriod
    has_active_schedule: bool


class DeviceDetail(BaseModel):
    id: UUID
    device_code: str
    device_nickname: str | None
    elderly_id: UUID
    my_role: Role
    timezone: str
    auto_sync_timezone: bool
    chime_volume_level: ChimeVolume
    config_version: int
    config_version_applied: int | None
    is_refill_mode: bool
    connectivity: Connectivity
    slots: list[DeviceSlotOut]


class DeviceUpdateIn(BaseModel):
    device_nickname: Name100 | None = None
    chime_volume_level: ChimeVolume | None = None
    timezone: TimeZoneName | None = None
    auto_sync_timezone: bool | None = None
    elderly_id: UUID | None = None


class DeviceUpdateOut(BaseModel):
    id: UUID
    device_nickname: str | None
    chime_volume_level: ChimeVolume
    timezone: str
    auto_sync_timezone: bool
    elderly_id: UUID
    config_version: int
    updated_at: datetime


class ChamberDoor(BaseModel):
    slot_number: int
    door: Literal["OPEN", "CLOSED"]


class DeviceStatusOut(BaseModel):
    device_id: UUID
    connectivity: Connectivity
    last_seen_at: datetime | None
    online_since: datetime | None
    offline_since: datetime | None
    wifi_strength: Literal["LEMAH", "SEDANG", "KUAT"] | None
    wifi_rssi_dbm: int | None
    battery_percent: int | None
    estimated_battery_days_remaining: float | None
    rtc_backup_active: bool | None
    command_channel_connected: bool
    chambers: list[ChamberDoor]


class ClockOut(BaseModel):
    device_id: UUID
    device_internal_time: datetime | None
    server_time: datetime
    drift_seconds: float | None
    is_accurate: bool | None
    auto_sync_timezone: bool
    reported_at: datetime | None


class CalibrateIn(BaseModel):
    device_pin: str


class CalibrateOut(BaseModel):
    device_id: UUID
    device_internal_time: datetime | None
    drift_seconds: float | None
    calibrated_at: datetime
    command_id: str


class AlarmIn(BaseModel):
    slot_number: int | None = Field(None, ge=1, le=8)
    duration_seconds: int = Field(60, ge=5, le=600)


class CommandResultOut(BaseModel):
    device_id: UUID
    command: str
    command_id: str
    acknowledged: bool
    acked_at: datetime
    result: dict[str, Any] | None


class DeviceEventOut(BaseModel):
    event_id: str
    event_type: str
    slot_number: int | None
    occurred_at: datetime
    received_at: datetime
    outcome: str
    reject_reason: str | None
    telemetry_log_id: UUID | None


class DeviceEventPage(BaseModel):
    data: list[DeviceEventOut]
    page: int
    limit: int
    total: int
