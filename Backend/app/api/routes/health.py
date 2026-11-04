import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SettingsDep
from app.db.session import get_db
from app.services.background import loop_health

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: SettingsDep) -> dict:
    """Liveness (always 200 while the process serves requests) plus background loop health:
    "degraded" when the rules engine or presence monitor finished no pass for a while."""
    loops = loop_health(settings)
    degraded = any(loop["status"] != "ok" for loop in loops.values())
    return {"status": "degraded" if degraded else "ok", "background": loops}


@router.get("/health/db")
async def health_db(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("health_db_failed", extra={"error": type(exc).__name__})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unreachable",
        ) from exc
    return {"status": "ok", "database": "reachable"}
