import asyncio
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any
from uuid import uuid4

from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def uses_transaction_pooler(settings: Settings) -> bool:
    """Supabase's transaction pooler listens on 6543 (session pooler / direct: 5432)."""
    if settings.db_pooler_mode != "auto":
        return settings.db_pooler_mode == "transaction"
    return make_url(settings.database_url).port == 6543


# Transaction pooler (port 6543): many clients share a few real Postgres
# connections, so the project-wide client cap of the session pooler (port 5432,
# "max clients reached in session mode") is no longer hit when several people
# run the backend against the same project. Each transaction may land on a
# different server connection, so prepared statements must not be cached and
# their names must be unique.
@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    url = make_url(settings.database_url)
    connect_args: dict[str, Any] = {
        "timeout": settings.db_connect_timeout_seconds,
        "command_timeout": settings.db_command_timeout_seconds,
        "server_settings": {"application_name": settings.app_name},
    }
    if uses_transaction_pooler(settings):
        url = url.update_query_dict({"prepared_statement_cache_size": "0"})
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"
    if settings.db_use_null_pool:
        return create_async_engine(url, echo=settings.debug, poolclass=NullPool, connect_args=connect_args)
    return create_async_engine(
        url,
        echo=settings.debug,
        connect_args=connect_args,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Fail fast with a 503 instead of queueing requests for 30 s when the pool is exhausted.
        pool_timeout=settings.db_pool_timeout_seconds,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def warm_pool() -> None:
    """Opens the pool's connections at startup, concurrently, so the first
    requests do not each pay a connect + TLS + auth handshake to the remote
    database. Failures are logged, never raised: the app still starts."""
    settings = get_settings()
    if settings.db_use_null_pool:
        return
    engine = get_engine()
    count = min(settings.db_pool_warm_connections, settings.db_pool_size)
    if count <= 0:
        return
    conns = [engine.connect() for _ in range(count)]

    async def _open(conn: AsyncConnection) -> None:
        await conn.start()
        await conn.execute(text("SELECT 1"))

    # All connections stay checked out until every one is open, so each is new.
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(_open(c) for c in conns), return_exceptions=True), timeout=15
        )
    except TimeoutError as exc:
        results = [exc]
    finally:
        await asyncio.gather(*(c.close() for c in conns), return_exceptions=True)
    failed = [r for r in results if isinstance(r, BaseException)]
    if failed:
        logger.warning("db_pool_warmup_failed", extra={"failed": len(failed), "error": repr(failed[0])})
    else:
        logger.info("db_pool_warmed", extra={"connections": count})
