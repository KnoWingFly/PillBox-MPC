"""Thin SQLite wrapper. Kept dependency-free (stdlib sqlite3 only) so the
core/scheduler and tests never need a running PySide6 app to exercise it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import uuid

from smart_pillbox import config
from smart_pillbox.models import Compartment

# Default schedule used only the very first time the DB is created, so a
# fresh checkout has something to demo immediately. Caregivers would edit
# this from the mobile app in the real system (Schedule Control screen).
_DEFAULT_SCHEDULE = [
    # (slot_number, meal_relation, meal_time, schedule_time)
    (1, "sebelum_makan", "pagi", "07:00"),
    (2, "sebelum_makan", "siang", "12:00"),
    (3, "sebelum_makan", "sore", "17:00"),
    (4, "sebelum_makan", "malam", "20:00"),
    (5, "sesudah_makan", "pagi", "07:30"),
    (6, "sesudah_makan", "siang", "12:30"),
    (7, "sesudah_makan", "sore", "17:30"),
    (8, "sesudah_makan", "malam", "20:30"),
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
        # Handle migration for existing databases smoothly
        try:
            self._conn.execute("ALTER TABLE compartments ADD COLUMN medication_name TEXT NULL")
            self._conn.execute("ALTER TABLE compartments ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            pass # Columns already exist

    def _seed_default_compartments_if_empty(self) -> None:
        count = self._conn.execute("SELECT COUNT(*) FROM compartments").fetchone()[0]
        if count > 0:
            return
        self._conn.executemany(
            "INSERT INTO compartments (slot_number, meal_relation, meal_time, schedule_time) VALUES (?, ?, ?, ?)",
            _DEFAULT_SCHEDULE,
        )
        self._conn.commit()

    # -- compartments ----------------------------------------------------------
    def get_compartments(self) -> list[Compartment]:
        rows = self._conn.execute(
            "SELECT id, slot_number, meal_relation, meal_time, schedule_time, tolerance_minutes, medication_name, is_active "
            "FROM compartments ORDER BY slot_number"
        ).fetchall()
        return [
            Compartment(
                id=row["id"],
                slot_number=row["slot_number"],
                meal_relation=row["meal_relation"],
                meal_time=row["meal_time"],
                schedule_time=row["schedule_time"],
                tolerance_minutes=row["tolerance_minutes"],
                medication_name=row["medication_name"],
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    def update_schedules(self, schedules: list[dict]) -> None:
        self._conn.execute("UPDATE compartments SET is_active = 0")
        for s in schedules:
            self._conn.execute(
                """UPDATE compartments 
                   SET schedule_time = ?, tolerance_minutes = ?, medication_name = ?, is_active = 1
                   WHERE slot_number = ?""",
                (s["schedule_time"], s["tolerance_minutes"], s.get("medication_name"), s["slot_number"])
            )
        self._conn.commit()

    # -- events / telemetry buffer ----------------------------------------------
    def log_event(self, compartment_id: int, slot_number: int, event_type: str, occurred_at: datetime, chime_count: int = 0) -> int:
        event_id = str(uuid.uuid4())
        cur = self._conn.execute(
            "INSERT INTO events (event_id, compartment_id, slot_number, event_type, occurred_at, chime_count) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, compartment_id, slot_number, event_type, occurred_at.isoformat(), chime_count),
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

    def mark_synced(self, db_ids: list[int]) -> None:
        if not db_ids:
            return
        placeholders = ",".join("?" for _ in db_ids)
        self._conn.execute(
            f"UPDATE events SET synced = 1 WHERE id IN ({placeholders})", db_ids
        )
        self._conn.commit()

    # -- device state -----------------------------------------------------------
    def get_device_state(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM device_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def update_device_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO device_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
