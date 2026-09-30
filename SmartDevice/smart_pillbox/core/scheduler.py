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
        self._load_compartments()
        self.active_chamber_id: int | None = None
        self._queue: list[int] = []
        self._actioned_today: set[tuple[int, str]] = set()  # (compartment_id, iso-date)

        # Refill mode
        self.is_refill_mode: bool = False

        # GUI (or tests) can append callables here; called with the Compartment.
        self.on_activated: list[Callable[[Compartment], None]] = []
        self.on_missed: list[Callable[[Compartment], None]] = []
        self.on_taken: list[Callable[[Compartment], None]] = []

    def _load_compartments(self):
        # Reload compartments from DB (used on startup and after config sync)
        compartments = self.db.get_compartments()
        self.compartments: dict[int, Compartment] = {c.id: c for c in compartments if c.is_active}

    # -- main loop, call this from a QTimer every ~1s --------------------------
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
        self.db.log_event(compartment.id, compartment.slot_number, "POPUP_ACTIVATED", now)
        for cb in self.on_activated:
            cb(compartment)

    def _check_tolerance(self, compartment: Compartment, now: datetime) -> None:
        assert compartment.activated_at is not None
        deadline = compartment.activated_at + timedelta(minutes=compartment.tolerance_minutes)
        if now >= deadline:
            compartment.state = ChamberState.MISSED
            compartment.door_open = False
            today_key = now.date().isoformat()
            self._actioned_today.add((compartment.id, today_key))
            self.db.log_event(compartment.id, compartment.slot_number, "ALARM_TIMEOUT", now)
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

    # -- hardware interactions ------------------------------------------------
    def open_compartment(self, compartment_id: int) -> None:
        compartment = self.compartments.get(compartment_id)
        if compartment is None:
            return
            
        now = self.clock.now()

        if self.is_refill_mode:
            compartment.door_open = True
            self.db.log_event(compartment_id, compartment.slot_number, "REFILL_MAINTENANCE", now)
            return
        
        if compartment.state == ChamberState.ACTIVE:
            # UX V2: Opening the lid means the pill is taken. No need to wait for close.
            compartment.state = ChamberState.TAKEN
            compartment.door_open = True
            if compartment.stock_count > 0:
                compartment.stock_count = self.db.update_stock(compartment.slot_number, -1)
            
            # Estimate chime count (assume 1 chime per second, up to 60 per minute)
            elapsed_seconds = (now - compartment.activated_at).total_seconds()
            chimes = int(elapsed_seconds / 2) # approx 1 every 2 seconds
            
            self.db.log_event(compartment_id, compartment.slot_number, "COMPARTMENT_OPENED", now, chime_count=chimes)
            
            self._actioned_today.add((compartment_id, now.date().isoformat()))
            if self.active_chamber_id == compartment_id:
                self.active_chamber_id = None
            for cb in self.on_taken:
                cb(compartment)
                
        elif compartment.state in (ChamberState.IDLE, ChamberState.TAKEN, ChamberState.MISSED):
            # Unscheduled open
            compartment.door_open = True
            self.db.log_event(compartment_id, compartment.slot_number, "UNSCHEDULED_OPEN", now)

    def refill_slot(self, slot_number: int, delta: int = 1) -> int:
        now = self.clock.now()
        new_stock = self.db.update_stock(slot_number, delta)
        for c in self.compartments.values():
            if c.slot_number == slot_number:
                c.stock_count = new_stock
                self.db.log_event(c.id, slot_number, "REFILL_MAINTENANCE", now)
                break
        return new_stock

    def unload_slot(self, slot_number: int, delta: int = 1) -> int:
        now = self.clock.now()
        new_stock = self.db.update_stock(slot_number, -delta)
        for c in self.compartments.values():
            if c.slot_number == slot_number:
                c.stock_count = new_stock
                self.db.log_event(c.id, slot_number, "REFILL_MAINTENANCE", now)
                break
        return new_stock

    def close_compartment(self, compartment_id: int) -> None:
        compartment = self.compartments.get(compartment_id)
        if compartment is None or not compartment.door_open:
            return

        now = self.clock.now()
        compartment.door_open = False
        
        if self.is_refill_mode:
            self.db.log_event(compartment_id, compartment.slot_number, "REFILL_MAINTENANCE", now)
        else:
            self.db.log_event(compartment_id, compartment.slot_number, "COMPARTMENT_CLOSED", now)

    def manual_release(self, compartment_id: int) -> None:
        """Simulates the mechanical fail-safe pinhole release: force-opens a
        compartment outside the normal schedule flow."""
        self.open_compartment(compartment_id)
        self.close_compartment(compartment_id)

    def reset_day(self) -> None:
        """For demo purposes: put every compartment back to IDLE."""
        for compartment in self.compartments.values():
            compartment.state = ChamberState.IDLE
            compartment.activated_at = None
            compartment.door_open = False
        self.active_chamber_id = None
        self._queue.clear()
        self._actioned_today.clear()

    def get_next_dose(self) -> Compartment | None:
        """Find the earliest upcoming compartment scheduled for today that is still IDLE.
        If all upcoming slots today have passed or are actioned, returns None.
        """
        now = self.clock.now()
        candidates: list[tuple[datetime, Compartment]] = []
        for c in self.compartments.values():
            if c.is_active and c.state == ChamberState.IDLE:
                sched_dt = _today_scheduled_datetime(c, now)
                if sched_dt >= now:
                    candidates.append((sched_dt, c))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1].slot_number))
        return candidates[0][1]

    def interact(self, compartment_id: int) -> None:
        """Compatibility wrapper for tests / direct interaction calls."""
        self.open_compartment(compartment_id)
