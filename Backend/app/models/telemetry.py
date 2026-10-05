from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class TelemetryLog(Base):
    """One row per scheduled dose (status != NULL), plus non-dose rows such as
    UNSCHEDULED_OPEN (status NULL). Dose rows are the API's "dose logs"."""

    __tablename__ = "telemetry_logs"

    id: Mapped[UUID] = uuid_pk()
    device_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id"))
    schedule_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("schedules.id"))
    slot_number: Mapped[int | None] = mapped_column(SmallInteger)
    event_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str | None] = mapped_column(String(10))
    delay_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chime_count: Mapped[int | None] = mapped_column(Integer)
    log_source: Mapped[str | None] = mapped_column(String(40))
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    confirmation_note: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    # --- migration 0002 additions -------------------------------------
    elderly_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("elderly.id"))
    scheduled_date: Mapped[date | None] = mapped_column(Date)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceEvent(Base):
    """Raw device event inbox; (device_id, event_id) is unique (idempotency)."""

    __tablename__ = "device_events"

    id: Mapped[UUID] = uuid_pk()
    device_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id"))
    event_id: Mapped[str] = mapped_column(String(64))
    batch_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(40))
    slot_number: Mapped[int | None] = mapped_column(SmallInteger)
    schedule_ref: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    chime_count: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(10))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    telemetry_log_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("telemetry_logs.id"))
    received_at: Mapped[datetime] = created_at_col()
