"""The on-device "Rules Engine": decides when a compartment pops up, enforces
the Single Active Chamber constraint, and flags MISSED after the tolerance
window. Deliberately has zero PySide6 imports so it's unit-testable with
plain pytest; the GUI layer wires its callbacks to Qt signals separately.

A dose window is [schedule_time, schedule_time + tolerance], the same window
the backend judges by (Backend/app/services/adherence.py). A chamber pops up
only inside it: when the simulator starts (or the clock jumps) after a window
has closed, that dose is MISSED without ringing instead of popping up hours
late. Today's TAKEN/MISSED states are rebuilt from the local event log at
start-up, at midnight and when the clock moves backwards (restore_day).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Callable

from smart_pillbox.db.database import Database
from smart_pillbox.core.rtc import SimulatedClock
from smart_pillbox.models import ChamberState, Compartment


def _today_scheduled_datetime(compartment: Compartment, today: datetime) -> datetime:
    hour, minute = map(int, compartment.schedule_time.split(":"))
    return today.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _deadline(compartment: Compartment, due_at: datetime) -> datetime:
    return due_at + timedelta(minutes=compartment.tolerance_minutes)


def _scheduled_on(compartment: Compartment, day: datetime) -> bool:
    """days_of_week uses 1=Monday ... 7=Sunday; an empty list means every day."""
    return compartment.is_active and (not compartment.days_of_week or day.isoweekday() in compartment.days_of_week)


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
        # Called after restore_day() rewrote the states of several chambers at once.
        self.on_restored: list[Callable[[], None]] = []

        self._day = None
        self._last_tick_at: datetime | None = None
        self.restore_day()

    def _load_compartments(self):
        # All 8 chambers are physical, so all are kept (and get a widget);
        # inactive ones simply never pop up (see tick()).
        compartments = self.db.get_compartments()
        self.compartments: dict[int, Compartment] = {c.id: c for c in compartments}

    def reload_schedules(self) -> None:
        """Applies a freshly pulled config (schedule time, tolerance, days,
        active flag) to the live chambers without losing their runtime state
        (an alarm that is ringing keeps ringing).

        A chamber whose timing changed is re-armed for today: otherwise a slot
        that was already TAKEN/MISSED today would ignore its new time until
        tomorrow, and the caregiver's change would look like it did nothing."""
        for fresh in self.db.get_compartments():
            current = self.compartments.get(fresh.id)
            if current is None:
                self.compartments[fresh.id] = fresh
                continue
            timing_changed = (
                current.schedule_time != fresh.schedule_time
                or current.days_of_week != fresh.days_of_week
                or current.is_active != fresh.is_active
            )
            rearm = timing_changed and current.state != ChamberState.ACTIVE
            if rearm:
                current.state = ChamberState.IDLE
                current.activated_at = None
                current.due_at = None
                self._actioned_today = {key for key in self._actioned_today if key[0] != current.id}
                if current.id in self._queue:
                    self._queue.remove(current.id)
            current.schedule_time = fresh.schedule_time
            current.tolerance_minutes = fresh.tolerance_minutes
            current.medication_name = fresh.medication_name
            current.days_of_week = fresh.days_of_week
            current.is_active = fresh.is_active
            if rearm:
                # A time whose window already closed today starts tomorrow, as on the backend
                # (it never creates doses from before the schedule existed): no instant MISSED.
                now = self.clock.now()
                if _scheduled_on(current, now) and now >= _deadline(current, _today_scheduled_datetime(current, now)):
                    self._actioned_today.add((current.id, now.date().isoformat()))

    def restore_day(self) -> None:
        """Rebuilds today's TAKEN/MISSED states from the event log (an ACTIVE chamber is left
        alone). Without it a restart forgets what happened today, so a dose already taken pops
        up again, and every morning dose pops up when the simulator is started in the evening."""
        now = self.clock.now()
        self._day = now.date()
        self._last_tick_at = now
        today_key = now.date().isoformat()
        self._actioned_today = set()
        self._queue.clear()
        outcomes: dict[int, list[tuple[datetime, str]]] = {}
        for row in self.db.get_events_between(datetime.combine(now.date(), time.min), now):
            if row["event_type"] in ("COMPARTMENT_OPENED", "ALARM_TIMEOUT"):
                outcomes.setdefault(row["compartment_id"], []).append(
                    (datetime.fromisoformat(row["occurred_at"]), row["event_type"])
                )

        for compartment in self.compartments.values():
            if compartment.state == ChamberState.ACTIVE:
                continue
            compartment.state = ChamberState.IDLE
            compartment.activated_at = None
            compartment.due_at = None
            compartment.release_until = None
            if not _scheduled_on(compartment, now):
                continue
            due_at = _today_scheduled_datetime(compartment, now)
            # Only events of the current schedule time count (a pop-up is never before it).
            seen = [etype for at, etype in outcomes.get(compartment.id, []) if at >= due_at]
            if seen:
                compartment.state = ChamberState.TAKEN if seen[-1] == "COMPARTMENT_OPENED" else ChamberState.MISSED
            elif now >= _deadline(compartment, due_at):
                compartment.state = ChamberState.MISSED  # the window closed while the device was off
            else:
                continue
            self._actioned_today.add((compartment.id, today_key))
        for cb in self.on_restored:
            cb()

    # -- main loop, call this from a QTimer every ~1s --------------------------
    def tick(self) -> None:
        now = self.clock.now()
        if self._last_tick_at is not None and (now.date() != self._day or now < self._last_tick_at - timedelta(seconds=1)):
            # Midnight (a new day of doses) or the clock was set back.
            self.restore_day()
        self._last_tick_at = now
        today_key = now.date().isoformat()

        for compartment in self.compartments.values():
            if compartment.state == ChamberState.ACTIVE:
                self._check_tolerance(compartment, now)
                continue

            if compartment.state != ChamberState.IDLE:
                continue  # already TAKEN/MISSED for today
            if not compartment.is_active:
                continue  # no schedule configured for this chamber
            if (compartment.id, today_key) in self._actioned_today:
                continue
            if not _scheduled_on(compartment, now):
                continue

            due_at = _today_scheduled_datetime(compartment, now)
            if now < due_at:
                continue
            if now >= _deadline(compartment, due_at):
                self._miss_unattended(compartment, now)  # the clock jumped past the whole window
            else:
                self._due(compartment, due_at, now)

        self._drain_queue_if_free()

    def _due(self, compartment: Compartment, due_at: datetime, now: datetime) -> None:
        compartment.due_at = due_at
        if self.active_chamber_id is None:
            self._activate(compartment, now)
        elif compartment.id not in self._queue:
            self._queue.append(compartment.id)  # Single Active Chamber: wait its turn

    def _miss_unattended(self, compartment: Compartment, now: datetime) -> None:
        """The window closed without this chamber ever popping up (clock jump, or queued behind
        another chamber). No ALARM_TIMEOUT: the device never rang; the backend's rules engine
        decides MISSED for the dose on its own."""
        compartment.state = ChamberState.MISSED
        self._actioned_today.add((compartment.id, now.date().isoformat()))
        if compartment.id in self._queue:
            self._queue.remove(compartment.id)
        for cb in self.on_missed:
            cb(compartment)

    def _activate(self, compartment: Compartment, now: datetime) -> None:
        compartment.state = ChamberState.ACTIVE
        compartment.activated_at = now
        self.active_chamber_id = compartment.id
        self.db.log_event(compartment.id, compartment.slot_number, "POPUP_ACTIVATED", now)
        for cb in self.on_activated:
            cb(compartment)

    def _check_tolerance(self, compartment: Compartment, now: datetime) -> None:
        assert compartment.activated_at is not None
        deadline = compartment.release_until or _deadline(compartment, compartment.due_at or compartment.activated_at)
        if now >= deadline:
            compartment.state = ChamberState.MISSED
            compartment.release_until = None
            compartment.door_open = False
            today_key = now.date().isoformat()
            self._actioned_today.add((compartment.id, today_key))
            # Stamped at the deadline, not "now": after a clock jump the timeout still lands
            # inside the dose window the backend matches it against.
            self.db.log_event(compartment.id, compartment.slot_number, "ALARM_TIMEOUT", min(now, deadline))
            if self.active_chamber_id == compartment.id:
                self.active_chamber_id = None
            for cb in self.on_missed:
                cb(compartment)

    def _drain_queue_if_free(self) -> None:
        while self.active_chamber_id is None and self._queue:
            compartment = self.compartments[self._queue.pop(0)]
            if compartment.state != ChamberState.IDLE:
                continue
            now = self.clock.now()
            if compartment.due_at is not None and now >= _deadline(compartment, compartment.due_at):
                self._miss_unattended(compartment, now)  # its whole window passed in the queue
            else:
                self._activate(compartment, now)

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
            compartment.release_until = None
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
        """For demo purposes: put every compartment back to IDLE. Doses whose window already
        closed today stay quiet (they would only turn MISSED); the rest pop up again on time."""
        now = self.clock.now()
        self._queue.clear()
        self._actioned_today.clear()
        for compartment in self.compartments.values():
            compartment.state = ChamberState.IDLE
            compartment.activated_at = None
            compartment.due_at = None
            compartment.release_until = None
            compartment.door_open = False
            if _scheduled_on(compartment, now) and now >= _deadline(compartment, _today_scheduled_datetime(compartment, now)):
                self._actioned_today.add((compartment.id, now.date().isoformat()))
        self.active_chamber_id = None

    def get_next_dose(self) -> Compartment | None:
        """Find the earliest upcoming compartment scheduled for today that is still IDLE.
        If all upcoming slots today have passed or are actioned, returns None.
        """
        now = self.clock.now()
        candidates: list[tuple[datetime, Compartment]] = []
        for c in self.compartments.values():
            if c.state == ChamberState.IDLE and _scheduled_on(c, now):
                sched_dt = _today_scheduled_datetime(c, now)
                if sched_dt >= now:
                    candidates.append((sched_dt, c))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1].slot_number))
        return candidates[0][1]

    def release_late(self, slot_number: int, until: datetime) -> str | None:
        """A caregiver re-opened a MISSED dose from the app ("Buka bilik sekarang", backend
        command release_slot): pop the chamber up again until `until`. Opening it then logs
        COMPARTMENT_OPENED, which the backend records as taken late. Returns why it cannot
        (shown to the caregiver), or None when the chamber popped up."""
        compartment = next((c for c in self.compartments.values() if c.slot_number == slot_number), None)
        now = self.clock.now()
        if compartment is None:
            return f"Slot {slot_number} tidak ada"
        if self.is_refill_mode:
            return "Pillbox sedang dalam mode isi ulang"
        if compartment.state == ChamberState.TAKEN:
            return f"Slot {slot_number} sudah tercatat diminum"
        if compartment.state == ChamberState.ACTIVE:
            return None  # already popped up
        if self.active_chamber_id is not None:
            return "Bilik lain sedang terbuka; coba lagi setelah selesai"
        if until <= now:
            return "Batas waktu sudah lewat"
        compartment.state = ChamberState.ACTIVE
        compartment.activated_at = now
        compartment.release_until = until
        self.active_chamber_id = compartment.id
        self._actioned_today.add((compartment.id, now.date().isoformat()))
        self.db.log_event(compartment.id, compartment.slot_number, "POPUP_ACTIVATED", now)
        for cb in self.on_activated:
            cb(compartment)
        return None

    def next_due_at(self) -> datetime | None:
        """When the next dose pops up (today or within the coming week); for the lab's
        "jump to next dose" control."""
        now = self.clock.now()
        today_key = now.date().isoformat()
        for offset in range(8):
            day = now + timedelta(days=offset)
            times = [
                _today_scheduled_datetime(c, day)
                for c in self.compartments.values()
                if _scheduled_on(c, day)
                and (offset > 0 or (c.state == ChamberState.IDLE and (c.id, today_key) not in self._actioned_today))
            ]
            upcoming = [t for t in times if t > now]
            if upcoming:
                return min(upcoming)
        return None

    def interact(self, compartment_id: int) -> None:
        """Compatibility wrapper for tests / direct interaction calls."""
        self.open_compartment(compartment_id)
