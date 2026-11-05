"""Background tasks started in the FastAPI lifespan.

Each loop runs one pass per interval. A failing pass is logged and the next one waits longer
(exponential backoff up to BACKGROUND_MAX_BACKOFF_SECONDS), so a database outage is not hammered.
A loop task that dies anyway (a bug outside the pass) is logged and restarted. /health reports
how long ago each loop last finished a pass (loop_health()).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services import presence
from app.services.leader import PRESENCE_LOCK_KEY, try_lead
from app.services.rules_engine import run_once

logger = logging.getLogger(__name__)

PRESENCE_LOOP = "presence_monitor"
RULES_ENGINE_LOOP = "rules_engine"


@dataclass
class LoopState:
    interval_seconds: float
    started_at: float
    last_success_at: float | None = None
    consecutive_failures: int = 0


_loops: dict[str, LoopState] = {}


def loop_health(settings: Settings) -> dict[str, dict[str, object]]:
    """Per loop: ok | stale (no finished pass within BACKGROUND_STALE_AFTER_INTERVALS intervals)."""
    now = time.monotonic()
    report: dict[str, dict[str, object]] = {}
    for name, state in _loops.items():
        reference = state.last_success_at if state.last_success_at is not None else state.started_at
        age = now - reference
        stale = age > state.interval_seconds * settings.background_stale_after_intervals
        report[name] = {
            "status": "stale" if stale else "ok",
            "seconds_since_last_pass": round(age, 1) if state.last_success_at is not None else None,
            "consecutive_failures": state.consecutive_failures,
        }
    return report


def _delay(state: LoopState, settings: Settings) -> float:
    if state.consecutive_failures == 0:
        return state.interval_seconds
    backoff = state.interval_seconds * (2 ** min(state.consecutive_failures, settings.background_max_backoff_exponent))
    return min(backoff, settings.background_max_backoff_seconds)


async def _run_forever(name: str, state: LoopState, run_pass: Callable[[], Awaitable[None]], settings: Settings) -> None:
    logger.info(f"{name}_started", extra={"interval_s": state.interval_seconds})
    while True:
        try:
            await run_pass()
            state.last_success_at = time.monotonic()
            state.consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            state.consecutive_failures += 1
            # Keep the loop alive (DB blips); the next pass retries idempotently.
            logger.exception(f"{name}_pass_failed", extra={"consecutive_failures": state.consecutive_failures})
        await asyncio.sleep(_delay(state, settings))


async def _presence_pass(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    async with sessionmaker() as session:
        if await try_lead(session, PRESENCE_LOCK_KEY):
            await presence.sweep(session, datetime.now(UTC), settings)


class MaterializeFailedError(Exception):
    """The pass decided MISSED doses but could not create the due ones (already logged)."""


async def _rules_engine_pass(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    result = await run_once(sessionmaker, datetime.now(UTC), settings)
    if result.created or result.missed:
        logger.info("rules_engine_pass", extra={"pending_created": result.created, "missed": result.missed})
    if result.materialize_failed:
        raise MaterializeFailedError  # counts as a failed pass: backoff and /health see it


def _start(
    name: str, interval: float, run_pass: Callable[[], Awaitable[None]], settings: Settings, tasks: list[asyncio.Task[None]]
) -> asyncio.Task[None]:
    state = _loops.setdefault(name, LoopState(interval_seconds=interval, started_at=time.monotonic()))
    task = asyncio.create_task(_run_forever(name, state, run_pass, settings), name=name)

    def _restart_if_died(done: asyncio.Task[None]) -> None:
        """_run_forever survives every failing pass; this covers a bug in the loop itself.
        Restarted after the backoff delay (never in a tight loop); shutdown cancels it."""
        if done.cancelled() or not isinstance(done.exception(), Exception):
            return  # cancelled at shutdown, or SystemExit/KeyboardInterrupt: let it go
        state.consecutive_failures += 1
        logger.error(f"{name}_task_died", exc_info=done.exception())

        def _restart() -> None:
            if name in _loops and done in tasks:  # not after stop_background_tasks()
                tasks[tasks.index(done)] = _start(name, interval, run_pass, settings, tasks)

        asyncio.get_running_loop().call_later(_delay(state, settings), _restart)

    task.add_done_callback(_restart_if_died)
    return task


def start_background_tasks(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> list[asyncio.Task[None]]:
    tasks: list[asyncio.Task[None]] = []
    tasks.append(
        _start(PRESENCE_LOOP, settings.presence_check_interval_seconds,
               lambda: _presence_pass(sessionmaker, settings), settings, tasks)
    )
    tasks.append(
        _start(RULES_ENGINE_LOOP, settings.rules_engine_interval_seconds,
               lambda: _rules_engine_pass(sessionmaker, settings), settings, tasks)
    )
    return tasks


async def stop_background_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in list(tasks):
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _loops.clear()
