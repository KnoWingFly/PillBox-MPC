"""Plain dataclasses shared between the DB layer, scheduler, and GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ChamberState(str, Enum):
    IDLE = "idle"          # flush, waiting for its schedule time
    ACTIVE = "active"      # popped up, LED breathing, chime sounding
    TAKEN = "taken"        # door opened -> done for this cycle
    MISSED = "missed"      # tolerance window expired without opening


@dataclass
class Compartment:
    id: int                     # primary key in db
    meal_relation: str          # "sebelum_makan" | "sesudah_makan"
    meal_time: str              # "pagi" | "siang" | "sore" | "malam"
    schedule_time: str          # "HH:MM"
    tolerance_minutes: int = 30
    medication_name: str | None = None
    stock_count: int = 0
    is_active: bool = True
    slot_number: int = 1        # mapped 1-8

    # --- runtime-only fields (not persisted directly on this row) ----------
    state: ChamberState = field(default=ChamberState.IDLE)
    activated_at: datetime | None = None   # when it popped up, for tolerance checks
    door_open: bool = False                # current Reed Switch reading

    @property
    def label(self) -> str:
        relation = "Sebelum" if self.meal_relation == "sebelum_makan" else "Sesudah"
        return f"Slot {self.slot_number}: {self.meal_time.capitalize()} ({relation})"


@dataclass
class Event:
    id: int
    event_id: str               # uuid
    compartment_id: int
    slot_number: int
    event_type: str             # POPUP_ACTIVATED, COMPARTMENT_OPENED, COMPARTMENT_CLOSED, ALARM_TIMEOUT, UNSCHEDULED_OPEN
    occurred_at: datetime
    chime_count: int = 0
    synced: bool = False
