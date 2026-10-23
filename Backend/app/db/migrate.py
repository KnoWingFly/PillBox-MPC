"""Minimal forward-only SQL migration runner.

Applies Backend/migrations/*.sql in filename order, each in its own
transaction, and records them in backend_schema_migrations (a separate table
from Prisma's _prisma_migrations, which the Mobile app owns).

Uses asyncpg directly because Connection.execute() without arguments runs
the simple-query protocol, which accepts multi-statement scripts.
"""

import hashlib
import logging
from pathlib import Path

import asyncpg

from app.core.config import BACKEND_DIR

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = BACKEND_DIR / "migrations"

_CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS backend_schema_migrations (
    filename    VARCHAR(255) PRIMARY KEY,
    checksum    VARCHAR(64) NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE backend_schema_migrations ENABLE ROW LEVEL SECURITY;
"""


def to_asyncpg_dsn(database_url: str) -> str:
    """asyncpg does not understand SQLAlchemy's '+asyncpg' driver suffix."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob("*.sql"))


async def apply_migrations(database_url: str, files: list[Path] | None = None) -> list[str]:
    """Returns the filenames applied by this call."""
    files = files if files is not None else migration_files()
    conn = await asyncpg.connect(to_asyncpg_dsn(database_url))
    applied_now: list[str] = []
    try:
        await conn.execute(_CREATE_LEDGER)
        rows = await conn.fetch("SELECT filename, checksum FROM backend_schema_migrations")
        applied = {row["filename"]: row["checksum"] for row in rows}
        for path in files:
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if path.name in applied:
                if applied[path.name] != checksum:
                    raise RuntimeError(
                        f"Migration {path.name} was modified after it was applied. "
                        "Add a new migration file instead of editing an applied one."
                    )
                continue
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO backend_schema_migrations (filename, checksum) VALUES ($1, $2)",
                    path.name,
                    checksum,
                )
            logger.info("migration_applied", extra={"migration": path.name})
            applied_now.append(path.name)
    finally:
        await conn.close()
    return applied_now
