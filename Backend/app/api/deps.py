import asyncio
import logging
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timing
from app.core.config import Settings, get_settings
from app.core.errors import AppError, unauthorized
from app.core.security import TokenConfigError, verify_app_token, verify_supabase_token
from app.db.session import get_db
from app.models import AuthIdentity, Device, User
from app.services.device_protocol import authenticate_device

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _claims(token: str, settings: Settings) -> dict[str, Any]:
    if settings.auth_mode == "app_jwt":
        return verify_app_token(token, settings)
    # PyJWKClient does blocking I/O on a cold cache.
    return await asyncio.to_thread(verify_supabase_token, token, settings)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: SettingsDep,
    db: DbSession,
) -> User:
    if credentials is None:
        raise unauthorized()
    return await user_from_token(credentials.credentials, settings, db)


async def user_from_token(token: str, settings: Settings, db: AsyncSession) -> User:
    """Verifies a caregiver access token and loads its user (REST and the app WebSocket)."""
    started = timing.now_ms()
    try:
        claims = await _claims(token, settings)
    except TokenConfigError:
        logger.error("auth_misconfigured", extra={"auth_mode": settings.auth_mode})
        raise AppError(500, "AUTH_MISCONFIGURED", "Server authentication is not configured") from None
    except jwt.PyJWKClientConnectionError:
        raise AppError(503, "AUTH_PROVIDER_UNREACHABLE", "Auth provider unreachable") from None
    except jwt.PyJWTError:
        raise unauthorized() from None

    try:
        subject = UUID(str(claims["sub"]))
    except (KeyError, ValueError):
        raise unauthorized() from None
    verified_ms = timing.since_ms(started)

    if settings.auth_mode == "app_jwt":
        user = await db.get(User, subject)
    else:
        user = (
            await db.execute(
                select(User)
                .join(AuthIdentity, AuthIdentity.user_id == User.id)
                .where(AuthIdentity.supabase_user_id == subject)
            )
        ).scalar_one_or_none()
    if user is None:
        # Token for a deleted (or never-synced) account is treated as invalid,
        # same as Mobile/src/server/users.ts getAuthedUser().
        raise unauthorized()
    # The first DB query of a request also pays for pool checkout (pre-ping) and BEGIN.
    timing.log_timing(
        "login", "backend_token_verified",
        verify_ms=verified_ms, user_lookup_ms=round(timing.since_ms(started) - verified_ms, 1),
    )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_authenticated_device(
    device_id: str,
    db: DbSession,
    x_device_key: Annotated[str | None, Header(alias="X-Device-Key")] = None,
) -> Device:
    """Device routes: path {device_id} is the device_code (or the device UUID),
    X-Device-Key is the per-device secret issued at provisioning. The row is
    locked here because every device route marks the device seen next."""
    return await authenticate_device(db, device_id, x_device_key, lock=True)


AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]


class Pagination:
    def __init__(
        self,
        settings: SettingsDep,
        page: Annotated[int, Query(ge=1)] = 1,
        limit: Annotated[int | None, Query(ge=1)] = None,
    ) -> None:
        self.page = page
        self.limit = min(limit or settings.default_page_limit, settings.max_page_limit)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


PaginationDep = Annotated[Pagination, Depends()]
