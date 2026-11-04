"""Brute-force guard for 4-digit device PINs and pairing scans (API List: 429 TOO_MANY_ATTEMPTS).

Counters live in Postgres (attempt_counters, migration 0007), so they survive a restart and are
shared by every process. A device PIN is limited per DEVICE across all users: creating more
accounts does not buy more guesses.

Each attempt is counted with one atomic upsert BEFORE the slow check runs, so N parallel guesses
cannot all pass the limit. Counting runs in its own short transaction: the caller's request
rolls back on a wrong PIN, and the count must stay.
"""

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.db.session import get_sessionmaker
from app.models import AttemptCounter
from app.models.enums import AttemptScope

_TOO_MANY = 429


async def register_attempt(
    scope: AttemptScope, subject: str, max_attempts: int, window_seconds: int, message: str
) -> None:
    """Counts one attempt. Raises 429 TOO_MANY_ATTEMPTS (with Retry-After) when this attempt is
    over the limit for the current window."""
    now = datetime.now(UTC)
    table = AttemptCounter.__table__
    expired = table.c.window_start <= now - timedelta(seconds=window_seconds)
    stmt = (
        insert(table)
        .values(scope=scope.value, subject_key=subject, attempts=1, window_start=now, updated_at=now)
        .on_conflict_do_update(
            constraint="attempt_counters_scope_subject_key",
            set_={
                "attempts": case((expired, 1), else_=table.c.attempts + 1),
                "window_start": case((expired, now), else_=table.c.window_start),
                "updated_at": now,
            },
        )
        .returning(table.c.attempts, table.c.window_start)
    )
    async with get_sessionmaker()() as session:
        attempts, window_start = (await session.execute(stmt)).one()
        await session.commit()
    if attempts > max_attempts:
        retry_after = (window_start + timedelta(seconds=window_seconds) - now).total_seconds()
        raise AppError(
            _TOO_MANY,
            "TOO_MANY_ATTEMPTS",
            message,
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )


async def reset(scope: AttemptScope, subject: str) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            delete(AttemptCounter).where(AttemptCounter.scope == scope.value, AttemptCounter.subject_key == subject)
        )
        await session.commit()
