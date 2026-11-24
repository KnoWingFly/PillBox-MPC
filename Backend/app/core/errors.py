"""One error envelope for the whole API, identical to the Mobile server's
(Mobile/src/server/http.ts): {"error": {"code", "message", "details"?}}.
The mobile client refreshes its token only on code UNAUTHORIZED, so keep
that code for invalid/expired caregiver tokens.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def unauthorized(code: str = "UNAUTHORIZED", message: str = "Authentication required") -> AppError:
    return AppError(401, code, message, headers={"WWW-Authenticate": "Bearer"})


def forbidden(code: str = "FORBIDDEN", message: str = "You do not have access to this action") -> AppError:
    return AppError(403, code, message)


def not_found(code: str = "NOT_FOUND", message: str = "Resource not found") -> AppError:
    return AppError(404, code, message)


def conflict(code: str, message: str, details: Any = None) -> AppError:
    return AppError(409, code, message, details)


def unprocessable(code: str, message: str, details: Any = None) -> AppError:
    return AppError(422, code, message, details)


# Database overloaded or unreachable (pool exhausted, pooler client limit, dropped
# connection, statement timeout). Answered with 503 + Retry-After instead of 500,
# so the app can tell "busy, try again" from a bug.
_DB_UNAVAILABLE = (sa_exc.TimeoutError, sa_exc.OperationalError, sa_exc.InterfaceError, OSError, TimeoutError)


# Postgres aborted the transaction to resolve a conflict (deadlock_detected, serialization_failure,
# lock_not_available from lock_timeout): safe to retry, so "busy" (503), not a bug (500).
_RETRYABLE_SQLSTATES = frozenset({"40P01", "40001", "55P03"})
_UNIQUE_VIOLATION = "23505"


def is_db_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, _DB_UNAVAILABLE):
        return True
    if isinstance(exc, sa_exc.DBAPIError):
        if exc.connection_invalidated:
            return True
        if getattr(exc.orig, "sqlstate", None) in _RETRYABLE_SQLSTATES:
            return True
        # Supavisor rejects with a FATAL that asyncpg maps to a generic error class.
        text = str(exc.orig).lower()
        return "max client" in text or "too many" in text or "timeout" in text
    return False


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    429: "TOO_MANY_REQUESTS",
    503: "SERVICE_UNAVAILABLE",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, jsonable_encoder(exc.details)),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"path": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("VALIDATION_ERROR", "Request validation failed", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)

    # Fallback only: UnhandledErrorMiddleware normally answers first (see its docstring).
    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        return unexpected_error_response(request, exc)


def unexpected_error_response(request: Request, exc: Exception) -> JSONResponse:
    """500, 503 (database busy) or 409 CONFLICT (unique-violation race) for an unhandled error."""
    if is_db_unavailable(exc):
        logger.warning(
            "db_unavailable",
            extra={"method": request.method, "path": request.url.path, "error": type(exc).__name__},
            # A bare OSError/TimeoutError may also be a bug outside the database: keep its trace.
            exc_info=False if isinstance(exc, sa_exc.SQLAlchemyError) else exc,
        )
        return JSONResponse(
            error_body("SERVICE_UNAVAILABLE", "Server is busy, please try again shortly"),
            status_code=503,
            headers={"Retry-After": str(get_settings().db_unavailable_retry_after_seconds)},
        )
    if isinstance(exc, sa_exc.IntegrityError) and getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION:
        # Two requests raced past a "does it exist yet?" check: the second one loses.
        logger.warning("unique_violation", extra={"method": request.method, "path": request.url.path})
        return JSONResponse(
            error_body("CONFLICT", "This was changed at the same time by another request, please reload"),
            status_code=409,
        )
    logger.error("unhandled_error", extra={"method": request.method, "path": request.url.path}, exc_info=exc)
    return JSONResponse(error_body("INTERNAL_ERROR", "Internal server error"), status_code=500)


class UnhandledErrorMiddleware:
    """Turns an unhandled exception into the API's error response *inside* CORSMiddleware.

    FastAPI's handler for `Exception` runs in Starlette's ServerErrorMiddleware, the outermost
    layer, so its 500/503/409 responses never pass through CORSMiddleware and a browser sees them
    as "server unreachable" (B2). Added before CORSMiddleware in main.py, this middleware sits
    inside it, so those responses carry the CORS headers like every other error.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started:  # the response is already under way: nothing sensible to send
                raise
            response = unexpected_error_response(Request(scope), exc)
            await response(scope, receive, send)
