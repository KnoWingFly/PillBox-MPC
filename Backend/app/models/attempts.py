from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, updated_at_col, uuid_pk


class AttemptCounter(Base):
    """Brute-force counter per (scope, subject_key); migration 0007, services/pin_attempts.py."""

    __tablename__ = "attempt_counters"

    id: Mapped[UUID] = uuid_pk()
    scope: Mapped[str] = mapped_column(String(20))
    subject_key: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = updated_at_col()
