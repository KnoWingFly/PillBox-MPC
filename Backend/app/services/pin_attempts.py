"""Brute-force guard for 4-digit device PINs (API List: 429 TOO_MANY_ATTEMPTS).

In-process memory: limits are per worker process and reset on restart.
Acceptable for a single-worker deployment (which the WebSocket connection
manager already requires); move to a DB/Redis counter if you scale out.
"""

import time
from collections import defaultdict, deque

from app.core.errors import AppError


class PinAttemptLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > window:
            q.popleft()
        return q

    def check(self, key: str, max_attempts: int, window_seconds: int) -> None:
        now = time.monotonic()
        q = self._prune(key, window_seconds, now)
        if len(q) >= max_attempts:
            retry_after = int(window_seconds - (now - q[0])) + 1
            raise AppError(
                429,
                "TOO_MANY_ATTEMPTS",
                "Too many incorrect PIN attempts, try again later",
                headers={"Retry-After": str(retry_after)},
            )

    def record_failure(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


pin_limiter = PinAttemptLimiter()
