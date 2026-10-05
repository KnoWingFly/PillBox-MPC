"""Background tasks started in the FastAPI lifespan."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services import presence
from app.services.rules_engine import rules_engine_loop

logger = logging.getLogger(__name__)


async def presence_loop(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    logger.info("presence_monitor_started", extra={"interval_s": settings.presence_check_interval_seconds})
    while True:
        try:
            async with sessionmaker() as session:
                await presence.sweep(session, datetime.now(UTC), settings)
        except Exception:
            logger.exception("presence_sweep_failed")
        await asyncio.sleep(settings.presence_check_interval_seconds)


def start_background_tasks(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> list[asyncio.Task[None]]:
    return [
        asyncio.create_task(presence_loop(sessionmaker, settings), name="presence_monitor"),
        asyncio.create_task(rules_engine_loop(sessionmaker, settings), name="rules_engine"),
    ]


async def stop_background_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
