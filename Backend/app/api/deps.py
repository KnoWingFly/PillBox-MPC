from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.security import verify_supabase_token

_bearer = HTTPBearer(auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]


class CurrentUser(BaseModel):
    id: UUID
    email: str | None = None
    role: str | None = None


# Sync on purpose: PyJWKClient does blocking I/O on a cold cache, and FastAPI
# runs sync dependencies in a threadpool so the event loop isn't blocked.
def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: SettingsDep,
) -> CurrentUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    try:
        claims = verify_supabase_token(credentials.credentials, settings)
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth provider unreachable",
        )
    except jwt.PyJWTError:
        raise unauthorized

    return CurrentUser(
        id=UUID(claims["sub"]),
        email=claims.get("email"),
        role=claims.get("role"),
    )
