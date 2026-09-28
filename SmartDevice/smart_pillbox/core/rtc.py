"""Simulated Real-Time Clock.

The real device keeps a hardware RTC running independently of Wi-Fi so the
pop-up schedule works offline. Here we simulate that with a plain Python
clock that can run at accelerated speed (so a demo doesn't need to wait
real hours between meal times) and can be manually jumped forward.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta


class SimulatedClock:
    def __init__(self, start_at: datetime | None = None, speed: float = 1.0):
        self._sim_start = start_at or datetime.now()
        self._wall_start = time.monotonic()
        self.speed = speed

    def now(self) -> datetime:
        elapsed_wall = time.monotonic() - self._wall_start
        elapsed_sim = elapsed_wall * self.speed
        return self._sim_start + timedelta(seconds=elapsed_sim)

    def set_speed(self, speed: float) -> None:
        # Re-anchor so changing speed mid-run doesn't jump time discontinuously.
        self._sim_start = self.now()
        self._wall_start = time.monotonic()
        self.speed = speed

    def jump(self, delta: timedelta) -> None:
        """Instantly move the simulated clock forward (or back) by delta."""
        self._sim_start = self.now() + delta
        self._wall_start = time.monotonic()

    def set_time(self, new_time: datetime) -> None:
        self._sim_start = new_time
        self._wall_start = time.monotonic()
