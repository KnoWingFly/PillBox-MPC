from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


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
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
