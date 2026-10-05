from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    elderly_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("elderly.id"))
    device_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id"))
    telemetry_log_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("telemetry_logs.id"))
    type: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_resolved: Mapped[bool] = mapped_column(Boolean, server_default="false")
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    event_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_col()
