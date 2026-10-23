from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, updated_at_col, uuid_pk


class Elderly(Base):
    __tablename__ = "elderly"

    id: Mapped[UUID] = uuid_pk()
    full_name: Mapped[str] = mapped_column(String(100))
    nickname: Mapped[str | None] = mapped_column(String(100))
    birth_date: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(10))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class UserElderlyRole(Base):
    __tablename__ = "user_elderly_roles"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    elderly_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("elderly.id"))
    role: Mapped[str] = mapped_column(String(10))
    relationship_label: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at_col()


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    elderly_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("elderly.id"))
    push_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    whatsapp_number: Mapped[str | None] = mapped_column(String(20))
    notify_on_missed: Mapped[bool] = mapped_column(Boolean, server_default="true")
    notify_on_taken: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notify_on_device_offline: Mapped[bool] = mapped_column(Boolean, server_default="true")
    device_offline_after_minutes: Mapped[int] = mapped_column(Integer, server_default="10")
    notify_on_low_battery: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[UUID] = uuid_pk()
    elderly_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("elderly.id"))
    invited_by_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    invitee_email: Mapped[str] = mapped_column(String(254))
    invitee_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(10))
    relationship_label: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = created_at_col()
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
