"""Payloads exchanged with the smart device (REST + WebSocket).
Field names follow the API List "[Perangkat]" rows; extra fields are additive
so the existing emulator keeps working. See docs/DEVICE_CONTRACT.md."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# --- heartbeat -----------------------------------------------------------
class ChamberStatus(BaseModel):
    slot_number: int = Field(..., ge=1, le=8)
    door: Literal["OPEN", "CLOSED"]
    # Physical sachet count reported by the device (emulator sends it).
    stock_count: int | None = Field(None, ge=0)


class HeartbeatRequest(BaseModel):
    sent_at: datetime | None = None
    battery_percent: int = Field(..., ge=0, le=100)
    wifi_rssi_dbm: int | None = None
    rtc_time: datetime | None = None
    config_version_applied: int | None = Field(None, ge=0)
    chambers: list[ChamberStatus] = Field(default_factory=list, max_length=8)
    rtc_backup_active: bool | None = None


class HeartbeatResponse(BaseModel):
    server_time: datetime
    latest_config_version: int
    config_update_available: bool
    heartbeat_interval_seconds: int
    # True once a caregiver has paired this device in the app.
    is_paired: bool


# --- config ----------------------------------------------------------------
class ScheduleConfig(BaseModel):
    schedule_id: str
    slot_number: int
    window_start: str  # "HH:MM"
    window_end: str
    tolerance_minutes: int
    days_of_week: list[int]
    active: bool
    medication_name: str | None
    dosage_info: str | None


class ConfigResponse(BaseModel):
    config_version: int
    timezone: str
    chime_volume_level: str
    is_refill_mode: bool
    schedules: list[ScheduleConfig]


class ConfigAckRequest(BaseModel):
    config_version: int = Field(..., ge=0)
    applied_at: datetime | None = None


class ConfigAckResponse(BaseModel):
    acknowledged: bool
    config_version_applied: int


# --- telemetry ---------------------------------------------------------------
class TelemetryEvent(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=64)
    # Kept as str so one unknown type is rejected per-event instead of the
    # whole batch failing validation (which would block the device's queue).
    event_type: str = Field(..., min_length=1, max_length=40)
    slot_number: int | None = Field(None, ge=1, le=8)
    schedule_id: str | None = Field(None, max_length=64)
    occurred_at: datetime
    chime_count: int | None = Field(None, ge=0)
    # BATTERY_STATUS
    battery_percent: int | None = Field(None, ge=0, le=100)
    on_external_power: bool | None = None
    # ALARM_STARTED / ALARM_STOPPED
    command_id: str | None = Field(None, max_length=64)
    reason: str | None = Field(None, max_length=200)


class TelemetryRequest(BaseModel):
    batch_id: str | None = Field(None, max_length=64)
    # True when the batch is a post-reconnect flush of the offline buffer.
    is_offline_flush: bool = False
    events: list[TelemetryEvent]


class RejectedEvent(BaseModel):
    event_id: str
    reason: str


class EventResult(BaseModel):
    event_id: str
    status: Literal["accepted", "duplicate", "rejected"]
    telemetry_log_id: str | None = None
    reason: str | None = None


class TelemetryResponse(BaseModel):
    server_time: datetime
    accepted: int
    duplicates: int
    rejected: list[RejectedEvent]
    latest_config_version: int
    # Per-event outcome in request order. For duplicates this is the ORIGINAL
    # outcome recorded when the event_id was first received.
    results: list[EventResult]
