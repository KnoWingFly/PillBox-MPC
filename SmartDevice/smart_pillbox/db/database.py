"""Thin SQLite wrapper. Kept dependency-free (stdlib sqlite3 only) so the
core/scheduler and tests never need a running PySide6 app to exercise it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from smart_pillbox import config
from smart_pillbox.models import Compartment

# Default schedule used only the very first time the DB is created, so a
# fresh checkout has something to demo immediately. Caregivers would edit
# this from the mobile app in the real system (Schedule Control screen).
_DEFAULT_SCHEDULE = [
    # (meal_relation,     meal_time, schedule_time)
    ("sebelum_makan", "pagi", "07:00"),
    ("sebelum_makan", "siang", "12:00"),
    ("sebelum_makan", "sore", "17:00"),
    ("sebelum_makan", "malam", "20:00"),
    ("sesudah_makan", "pagi", "07:30"),
    ("sesudah_makan", "siang", "12:30"),
    ("sesudah_makan", "sore", "17:30"),
    ("sesudah_makan", "malam", "20:30"),
]


class Database:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or config.DB_PATH)
        # check_same_thread=False: QTimer callbacks and any future sync
        # thread all share this single connection in the MVP.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._seed_default_compartments_if_empty()

    # -- setup ---------------------------------------------------------------
    def _init_schema(self) -> None:
        sql = config.SCHEMA_PATH.read_text()
        self._conn.executescript(sql)
        self._conn.commit()

    def _seed_default_compartments_if_empty(self) -> None:
        count = self._conn.execute("SELECT COUNT(*) FROM compartments").fetchone()[0]
        if count > 0:
            return
        self._conn.executemany(
            "INSERT INTO compartments (meal_relation, meal_time, schedule_time) VALUES (?, ?, ?)",
            _DEFAULT_SCHEDULE,
        )
        self._conn.commit()

    # -- compartments ----------------------------------------------------------
    def get_compartments(self) -> list[Compartment]:
        rows = self._conn.execute(
            "SELECT id, meal_relation, meal_time, schedule_time, tolerance_minutes, refill_units "
            "FROM compartments ORDER BY meal_time, meal_relation"
        ).fetchall()
        return [
            Compartment(
                id=row["id"],
                meal_relation=row["meal_relation"],
                meal_time=row["meal_time"],
                schedule_time=row["schedule_time"],
                tolerance_minutes=row["tolerance_minutes"],
                refill_units=row["refill_units"],
            )
            for row in rows
        ]

    def update_schedule(self, compartment_id: int, schedule_time: str, tolerance_minutes: int) -> None:
        self._conn.execute(
            "UPDATE compartments SET schedule_time = ?, tolerance_minutes = ? WHERE id = ?",
            (schedule_time, tolerance_minutes, compartment_id),
        )
        self._conn.commit()

    # -- events / telemetry buffer ----------------------------------------------
    def log_event(self, compartment_id: int, event_type: str, occurred_at: datetime) -> int:
        cur = self._conn.execute(
            "INSERT INTO events (compartment_id, event_type, occurred_at) VALUES (?, ?, ?)",
            (compartment_id, event_type, occurred_at.isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_events_for_compartment_since(
        self, compartment_id: int, since: datetime
    ) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM events WHERE compartment_id = ? AND occurred_at >= ? ORDER BY occurred_at",
            (compartment_id, since.isoformat()),
        ).fetchall()

    def get_unsynced_events(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM events WHERE synced = 0 ORDER BY occurred_at"
        ).fetchall()

    def mark_synced(self, event_ids: list[int]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        self._conn.execute(
            f"UPDATE events SET synced = 1 WHERE id IN ({placeholders})", event_ids
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
