"""The on-device "Rules Engine": decides when a compartment pops up, enforces
the Single Active Chamber constraint, and flags MISSED after the tolerance
window. Deliberately has zero PySide6 imports so it's unit-testable with
plain pytest; the GUI layer wires its callbacks to Qt signals separately.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from smart_pillbox.db.database import Database
from smart_pillbox.core.rtc import SimulatedClock
from smart_pillbox.models import ChamberState, Compartment


def _today_scheduled_datetime(compartment: Compartment, today: datetime) -> datetime:
    hour, minute = map(int, compartment.schedule_time.split(":"))
    return today.replace(hour=hour, minute=minute, second=0, microsecond=0)


class PillboxScheduler:
    def __init__(self, db: Database, clock: SimulatedClock):
        self.db = db
        self.clock = clock
        self.compartments: dict[int, Compartment] = {c.id: c for c in db.get_compartments()}

        self.active_chamber_id: int | None = None
        self._queue: list[int] = []
        self._actioned_today: set[tuple[int, str]] = set()  # (compartment_id, iso-date)

        # GUI (or tests) can append callables here; called with the Compartment.
        self.on_activated: list[Callable[[Compartment], None]] = []
        self.on_missed: list[Callable[[Compartment], None]] = []
        self.on_taken: list[Callable[[Compartment], None]] = []

    # -- main loop, call this from a QTimer every ~1s --------------------------
    def tick(self) -> None:
        now = self.clock.now()
        today_key = now.date().isoformat()

        for compartment in self.compartments.values():
            if compartment.state == ChamberState.ACTIVE:
                self._check_tolerance(compartment, now)
                continue

            if compartment.state != ChamberState.IDLE:
                continue  # already TAKEN/MISSED for today
            if (compartment.id, today_key) in self._actioned_today:
                continue

            scheduled_at = _today_scheduled_datetime(compartment, now)
            if now >= scheduled_at:
                self._due(compartment, now)

        self._drain_queue_if_free()

    def _due(self, compartment: Compartment, now: datetime) -> None:
        if self.active_chamber_id is None:
            self._activate(compartment, now)
        elif compartment.id not in self._queue:
            self._queue.append(compartment.id)  # Single Active Chamber: wait its turn

    def _activate(self, compartment: Compartment, now: datetime) -> None:
        compartment.state = ChamberState.ACTIVE
        compartment.activated_at = now
        self.active_chamber_id = compartment.id
        self.db.log_event(compartment.id, "POP_UP", now)
        for cb in self.on_activated:
            cb(compartment)

    def _check_tolerance(self, compartment: Compartment, now: datetime) -> None:
        assert compartment.activated_at is not None
        deadline = compartment.activated_at + timedelta(minutes=compartment.tolerance_minutes)
        if now >= deadline:
            compartment.state = ChamberState.MISSED
            today_key = now.date().isoformat()
            self._actioned_today.add((compartment.id, today_key))
            self.db.log_event(compartment.id, "MISSED", now)
            if self.active_chamber_id == compartment.id:
                self.active_chamber_id = None
            for cb in self.on_missed:
                cb(compartment)

    def _drain_queue_if_free(self) -> None:
        if self.active_chamber_id is not None or not self._queue:
            return
        next_id = self._queue.pop(0)
        compartment = self.compartments[next_id]
        if compartment.state == ChamberState.IDLE:
            self._activate(compartment, self.clock.now())

    # -- called from the GUI when the user "opens then closes" a compartment --
    def interact(self, compartment_id: int) -> None:
        compartment = self.compartments.get(compartment_id)
        if compartment is None or compartment.state != ChamberState.ACTIVE:
            return  # ignore taps on non-active compartments (no cognitive overload)

        now = self.clock.now()
        self.db.log_event(compartment_id, "DOOR_OPEN", now)
        self.db.log_event(compartment_id, "DOOR_CLOSE", now)
        self.db.log_event(compartment_id, "TAKEN", now)

        compartment.state = ChamberState.TAKEN
        compartment.door_open = False
        self._actioned_today.add((compartment_id, now.date().isoformat()))
        if self.active_chamber_id == compartment_id:
            self.active_chamber_id = None

        for cb in self.on_taken:
            cb(compartment)

    def manual_release(self, compartment_id: int) -> None:
        """Simulates the mechanical fail-safe pinhole release: force-opens a
        compartment outside the normal schedule flow."""
        compartment = self.compartments.get(compartment_id)
        if compartment is None:
            return
        now = self.clock.now()
        self.db.log_event(compartment_id, "DOOR_OPEN", now)
        self.db.log_event(compartment_id, "DOOR_CLOSE", now)
        compartment.door_open = False

    def reset_day(self) -> None:
        """For demo purposes: put every compartment back to IDLE."""
        for compartment in self.compartments.values():
            compartment.state = ChamberState.IDLE
            compartment.activated_at = None
        self.active_chamber_id = None
        self._queue.clear()
        self._actioned_today.clear()
