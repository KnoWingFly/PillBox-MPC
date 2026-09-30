from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# --- Heartbeat Schemas ---
class ChamberStatus(BaseModel):
    slot_number: int = Field(..., ge=1, le=8)
    door: str = Field(..., description="CLOSED or OPEN")
    stock_count: Optional[int] = Field(None, ge=0, le=30, description="Remaining sachet stock in compartment")

class HeartbeatRequest(BaseModel):
    sent_at: datetime
    battery_percent: int = Field(..., ge=0, le=100)
    wifi_rssi_dbm: int
    rtc_time: datetime
    config_version_applied: int
    chambers: List[ChamberStatus]

class HeartbeatResponse(BaseModel):
    server_time: datetime
    latest_config_version: int
    config_update_available: bool

# --- Config Pull Schemas ---
class ScheduleConfig(BaseModel):
    schedule_id: str
    slot_number: int = Field(..., ge=1, le=8)
    window_start: str
    window_end: str
    tolerance_minutes: int
    days_of_week: List[int]
    active: bool

class ConfigResponse(BaseModel):
    config_version: int
    timezone: str
    schedules: List[ScheduleConfig]

# --- Config ACK Schemas ---
class ConfigAckRequest(BaseModel):
    config_version: int
    applied_at: datetime

class ConfigAckResponse(BaseModel):
    acknowledged: bool
    config_version_applied: int

# --- Telemetry Schemas ---
class TelemetryEvent(BaseModel):
    event_id: str
    event_type: str  # POPUP_ACTIVATED | COMPARTMENT_OPENED | COMPARTMENT_CLOSED | ALARM_TIMEOUT | UNSCHEDULED_OPEN | REFILL_MAINTENANCE
    slot_number: Optional[int] = Field(None, ge=1, le=8)
    schedule_id: Optional[str] = None
    occurred_at: datetime
    chime_count: Optional[int] = 0

class TelemetryRequest(BaseModel):
    batch_id: str
    events: List[TelemetryEvent]

class TelemetryResponse(BaseModel):
    server_time: datetime
    accepted: int
    duplicates: int
    rejected: List[str]
    latest_config_version: int
