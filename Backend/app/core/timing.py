"""Opt-in latency instrumentation (PERF_TIMING_LOGS=true).

Every line is a structured log record with message "perf_timing" and the
fields: flow, step, correlation_id, and duration_ms / lag_ms where they
apply. Only ids, counts and durations are logged: never tokens, keys, PINs,
names or message text.

Flows and their correlation ids:
  iot_to_app    event_id from the device (follows the event into the
                notification rows; the app logs notification ids)
  app_to_iot    X-Correlation-ID sent by the app (falls back to request id)
  login         X-Correlation-ID sent by the app

When disabled, each call is one cached-settings attribute check.
"""

import logging
import time
from contextvars import ContextVar
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("app.perf")

# Set by the HTTP middleware (X-Correlation-ID or request id) and, during
# telemetry ingestion, to the event_id being applied.
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def enabled() -> bool:
    return get_settings().perf_timing_logs


def now_ms() -> float:
    return time.perf_counter() * 1000


def since_ms(started_ms: float) -> float:
    return round(now_ms() - started_ms, 1)


def log_timing(flow: str, step: str, *, correlation_id: str | None = None, **fields: Any) -> None:
    if not enabled():
        return
    logger.info(
        "perf_timing",
        extra={"flow": flow, "step": step, "correlation_id": correlation_id or correlation_id_var.get(), **fields},
    )
