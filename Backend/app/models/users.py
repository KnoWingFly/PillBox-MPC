"""Tables owned by Prisma (Mobile/prisma/schema.prisma). Mapped read-only:
the backend never creates or alters users/push_tokens rows, and only maps
the columns it reads."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    full_name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    phone_number: Mapped[str | None] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String)
    # Postgres enum "interface_language" ('ID' | 'EN'); asyncpg returns it as str.
    interface_language: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthIdentity(Base):
    __tablename__ = "auth_identities"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    supabase_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class PushToken(Base):
    __tablename__ = "push_tokens"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    token: Mapped[str] = mapped_column(String)
    # Postgres enum "push_platform" ('ANDROID' | 'IOS')
    platform: Mapped[str] = mapped_column(String)
