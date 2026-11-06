"""Simulated Real-Time Clock.

The real device keeps a hardware RTC running independently of Wi-Fi so the
pop-up schedule works offline. Here we simulate that with a plain Python
clock that can run at accelerated speed (so a demo doesn't need to wait
real hours between meal times) and can be manually jumped forward.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta


class SimulatedClock:
    """Read by the GUI thread and the sync worker (heartbeat rtc_time), moved by the GUI: the
    anchor (start, wall start, speed) changes under a lock so a reader never sees half of it."""

    def __init__(self, start_at: datetime | None = None, speed: float = 1.0):
        self._lock = threading.Lock()
        self._sim_start = start_at or datetime.now()
        self._wall_start = time.monotonic()
        self._speed = speed

    @property
    def speed(self) -> float:
        with self._lock:
            return self._speed

    def now(self) -> datetime:
        with self._lock:
            return self._now_locked()

    def _now_locked(self) -> datetime:
        elapsed_wall = time.monotonic() - self._wall_start
        return self._sim_start + timedelta(seconds=elapsed_wall * self._speed)

    def set_speed(self, speed: float) -> None:
        # Re-anchor so changing speed mid-run doesn't jump time discontinuously.
        with self._lock:
            self._sim_start = self._now_locked()
            self._wall_start = time.monotonic()
            self._speed = speed

    def jump(self, delta: timedelta) -> None:
        """Instantly move the simulated clock forward (or back) by delta."""
        with self._lock:
            self._sim_start = self._now_locked() + delta
            self._wall_start = time.monotonic()

    def set_time(self, new_time: datetime) -> None:
        with self._lock:
            self._sim_start = new_time
            self._wall_start = time.monotonic()
