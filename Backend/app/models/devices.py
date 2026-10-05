from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Time
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, updated_at_col, uuid_pk


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[UUID] = uuid_pk()
    device_code: Mapped[str] = mapped_column(String(64), unique=True)
    elderly_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("elderly.id"))
    master_password_hash: Mapped[str | None] = mapped_column(String(255))
    device_pin_hash: Mapped[str | None] = mapped_column(String(255))
    device_nickname: Mapped[str | None] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Jakarta")
    auto_sync_timezone: Mapped[bool] = mapped_column(Boolean, server_default="true")
    chime_volume_level: Mapped[str] = mapped_column(String(10), server_default="MEDIUM")
    status: Mapped[str] = mapped_column(String(10), server_default="OFFLINE")
    battery_percentage: Mapped[int | None] = mapped_column(Integer)
    config_version: Mapped[int] = mapped_column(Integer, server_default="1")
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    # --- migration 0002 additions -------------------------------------
    device_secret_hash: Mapped[str | None] = mapped_column(String(64))
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pin_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_version_applied: Mapped[int | None] = mapped_column(Integer)
    config_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_refill_mode: Mapped[bool] = mapped_column(Boolean, server_default="false")
    wifi_rssi_dbm: Mapped[int | None] = mapped_column(Integer)
    rtc_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rtc_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rtc_backup_active: Mapped[bool | None] = mapped_column(Boolean)
    chamber_doors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    online_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offline_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    low_battery_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[UUID] = uuid_pk()
    device_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id"))
    slot_number: Mapped[int] = mapped_column(SmallInteger)
    row_type: Mapped[str] = mapped_column(String(1))
    day_period: Mapped[str] = mapped_column(String(10))
    medication_name: Mapped[str | None] = mapped_column(String(100))
    dosage_info: Mapped[str | None] = mapped_column(String(255))
    window_start: Mapped[time] = mapped_column(Time)
    window_end: Mapped[time] = mapped_column(Time)
    tolerance_minutes: Mapped[int] = mapped_column(SmallInteger)
    days_of_week: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class DeviceStock(Base):
    __tablename__ = "device_stocks"

    id: Mapped[UUID] = uuid_pk()
    device_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id"))
    slot_number: Mapped[int] = mapped_column(SmallInteger)
    remaining_units: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = updated_at_col()


class Refill(Base):
    __tablename__ = "refills"

    id: Mapped[UUID] = uuid_pk()
    device_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id"))
    refilled_by_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    refilled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_reset: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = created_at_col()


class RefillItem(Base):
    __tablename__ = "refill_items"

    id: Mapped[UUID] = uuid_pk()
    refill_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("refills.id"))
    slot_number: Mapped[int] = mapped_column(SmallInteger)
    unit_dose_count: Mapped[int] = mapped_column(Integer)
