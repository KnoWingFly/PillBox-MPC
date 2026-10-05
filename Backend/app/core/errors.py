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
from starlette.exceptions import HTTPException as StarletteHTTPException

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

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error", extra={"method": request.method, "path": request.url.path}
        )
        return JSONResponse(error_body("INTERNAL_ERROR", "Internal server error"), status_code=500)
