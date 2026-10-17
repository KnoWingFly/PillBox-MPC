import asyncio
import logging
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# Session pooler (port 5432) supports prepared statements, so asyncpg defaults
# are fine. If you ever switch to the transaction pooler (port 6543), also set
# connect_args={"statement_cache_size": 0} and add
# ?prepared_statement_cache_size=0 to the URL.
@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    if settings.db_use_null_pool:
        return create_async_engine(settings.database_url, echo=settings.debug, poolclass=NullPool)
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
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
    conns = [engine.connect() for _ in range(settings.db_pool_size)]

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
        logger.info("db_pool_warmed", extra={"connections": settings.db_pool_size})
