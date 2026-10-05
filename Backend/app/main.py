import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    device_protocol,
    devices,
    elderly,
    health,
    journal,
    me,
    notifications,
    schedules,
    ws,
)
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.db.session import get_engine, get_sessionmaker
from app.services.background import start_background_tasks, stop_background_tasks

settings = get_settings()  # only used to configure the app object itself
configure_logging(settings.log_level, settings.log_json)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    tasks = start_background_tasks(get_sessionmaker(), settings) if settings.enable_background_tasks else []
    logger.info("startup", extra={"background_tasks": len(tasks), "auth_mode": settings.auth_mode})
    try:
        yield
    finally:
        await stop_background_tasks(tasks)
        await get_engine().dispose()  # creating the engine is lazy; no connection is opened


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
install_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    # Path only: query strings and headers (device keys, tokens) are never logged.
    logger.info(
        "http_request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response


app.include_router(health.router)
app.include_router(ws.router)

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(me.router)
api_v1.include_router(device_protocol.router)
api_v1.include_router(devices.router)
api_v1.include_router(schedules.router)
api_v1.include_router(elderly.router)
api_v1.include_router(journal.router)
api_v1.include_router(notifications.router)
api_v1.include_router(admin.router)
app.include_router(api_v1)
