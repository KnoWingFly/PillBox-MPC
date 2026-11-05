from typing import Any

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column


class Base(DeclarativeBase):
    # Server-side values (ids, created_at, updated_at onupdate=now()) come back with RETURNING in
    # the same INSERT/UPDATE, so services never need a refresh() round trip to read them.
    __mapper_args__ = {"eager_defaults": True}


def uuid_pk() -> MappedColumn[Any]:
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def created_at_col() -> MappedColumn[Any]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at_col() -> MappedColumn[Any]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
