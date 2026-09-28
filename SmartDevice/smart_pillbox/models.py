"""Plain dataclasses shared between the DB layer, scheduler, and GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ChamberState(str, Enum):
    IDLE = "idle"          # flush, waiting for its schedule time
    ACTIVE = "active"      # popped up, LED breathing, chime sounding
    TAKEN = "taken"        # closed again in time -> done for this cycle
    MISSED = "missed"      # tolerance window expired without a close event


@dataclass
class Compartment:
    id: int
    meal_relation: str          # "sebelum_makan" | "sesudah_makan"
    meal_time: str              # "pagi" | "siang" | "sore" | "malam"
    schedule_time: str          # "HH:MM"
    tolerance_minutes: int = 30
    refill_units: int = 0

    # --- runtime-only fields (not persisted directly on this row) ----------
    state: ChamberState = field(default=ChamberState.IDLE)
    activated_at: datetime | None = None   # when it popped up, for tolerance checks
    door_open: bool = False                # current Reed Switch reading

    @property
    def label(self) -> str:
        relation = "Sebelum Makan" if self.meal_relation == "sebelum_makan" else "Sesudah Makan"
        return f"{self.meal_time.capitalize()} — {relation}"


@dataclass
class Event:
    id: int
    compartment_id: int
    event_type: str
    occurred_at: datetime
    synced: bool = False
