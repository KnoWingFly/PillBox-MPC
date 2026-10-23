"""Runs each background pass on one backend instance only."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Advisory lock keys (arbitrary, project-wide constants).
PRESENCE_LOCK_KEY = 0x50_43_01  # "PC" 1
RULES_ENGINE_LOCK_KEY = 0x50_43_02  # "PC" 2


async def try_lead(session: AsyncSession, key: int) -> bool:
    """Every running backend shares one database, but a background pass only needs to
    run once: whoever takes this lock does it, the others skip the round. A
    transaction-scoped lock (released at commit/rollback) also works through the
    Supabase transaction pooler, unlike a session lock."""
    return bool(await session.scalar(select(func.pg_try_advisory_xact_lock(key))))
