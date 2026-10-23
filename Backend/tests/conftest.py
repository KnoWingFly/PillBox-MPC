"""Test setup: a REAL Postgres database from TEST_DATABASE_URL.

Safety: the database name must contain "test" and must differ from
DATABASE_URL, because the session fixture DROPS and recreates its public
schema, then applies the Prisma migrations (users, push_tokens, ...) and the
backend migrations exactly as production does.

The app runs in-process through httpx.ASGITransport (no lifespan, so the
background loops do not start; tests call the rules engine directly).
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
PRISMA_MIGRATIONS = REPO_DIR / "Mobile" / "prisma" / "migrations"

_dotenv = {k.upper(): v for k, v in dotenv_values(BACKEND_DIR / ".env").items() if v}
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or _dotenv.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.exit("TEST_DATABASE_URL is not set (see Backend/README.md, 'Tests').", returncode=2)

_db_name = urlparse(TEST_DATABASE_URL.replace("+asyncpg", "")).path.lstrip("/")
if "test" not in _db_name.lower():
    pytest.exit(f"Refusing to run: test database name {_db_name!r} must contain 'test'.", returncode=2)
_prod_url = os.environ.get("DATABASE_URL") or _dotenv.get("DATABASE_URL")
if _prod_url and _prod_url.split("://", 1)[-1] == TEST_DATABASE_URL.split("://", 1)[-1]:
    pytest.exit("Refusing to run: TEST_DATABASE_URL equals DATABASE_URL.", returncode=2)

from tests.constants import TEST_JWT_SECRET, TEST_PROVISIONING_TOKEN  # noqa: E402

# Real env vars beat Backend/.env in Settings, so this pins the app to the test DB.
os.environ.update(
    {
        "DATABASE_URL": TEST_DATABASE_URL,
        "AUTH_MODE": "app_jwt",
        "JWT_ACCESS_SECRET": TEST_JWT_SECRET,
        "PROVISIONING_TOKEN": TEST_PROVISIONING_TOKEN,
        "ENABLE_BACKGROUND_TASKS": "false",
        "DB_USE_NULL_POOL": "true",
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
        "COMMAND_ACK_TIMEOUT_SECONDS": "1",
    }
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402

from app.db.migrate import apply_migrations, to_asyncpg_dsn  # noqa: E402
from app.main import app  # noqa: E402
from app.services.connection_manager import connection_manager  # noqa: E402
from app.services.pin_attempts import pin_limiter  # noqa: E402

DSN = to_asyncpg_dsn(
    TEST_DATABASE_URL.replace("postgres://", "postgresql://", 1)
    if TEST_DATABASE_URL.startswith("postgres://")
    else TEST_DATABASE_URL
)

_TABLES = (
    "device_events, notifications, telemetry_logs, refill_items, refills, device_stocks, schedules, "
    "devices, invitations, notification_preferences, user_elderly_roles, elderly, push_tokens, users"
)


async def _reset_schema() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        for migration in sorted(PRISMA_MIGRATIONS.glob("*/migration.sql")):
            await conn.execute(migration.read_text(encoding="utf-8"))
    finally:
        await conn.close()
    await apply_migrations(DSN)


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> None:
    asyncio.run(_reset_schema())


@pytest.fixture(autouse=True)
async def clean_state() -> AsyncIterator[None]:
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(f"TRUNCATE {_TABLES} CASCADE")
    finally:
        await conn.close()
    pin_limiter._failures.clear()
    connection_manager._connections.clear()
    yield


@pytest.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    """Raw connection for test setup/assertions (not used by the app)."""
    conn = await asyncpg.connect(DSN)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

