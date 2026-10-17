"""Thin SQLite wrapper. Kept dependency-free (stdlib sqlite3 only) so the
core/scheduler and tests never need a running PySide6 app to exercise it.
"""

from __future__ import annotations

import functools
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
import json
import re
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


def _locked(method):
    """Runs the method while holding the connection lock. The GUI thread and the sync worker share
    one connection; sqlite3 allows that (check_same_thread=False) but not using it at the same
    moment, which fails with "InterfaceError: bad parameter or other API misuse"."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


def _event_types(schema_sql: str) -> list[str]:
    """The event types allowed by the events CHECK constraint in schema.sql."""
    code = "\n".join(line.split("--")[0] for line in schema_sql.splitlines())  # drop SQL comments first
    start = code.index("event_type IN (")
    return re.findall(r"'([A-Z_]+)'", code[start : code.index(")", start)])


class Database:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or config.DB_PATH)
        # check_same_thread=False: QTimer callbacks and any future sync
        # thread all share this single connection in the MVP.
        self._lock = threading.RLock()  # see _locked
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._seed_default_compartments_if_empty()

    # -- setup ---------------------------------------------------------------
    def _init_schema(self) -> None:
        sql = config.SCHEMA_PATH.read_text()
        self._retire_stale_events_table()
        self._conn.executescript(sql)
        self._restore_retired_events()
        self._conn.commit()
        # Handle migration for existing databases smoothly
        try:
            self._conn.execute("ALTER TABLE compartments ADD COLUMN medication_name TEXT NULL")
            self._conn.execute("ALTER TABLE compartments ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            pass # Columns already exist
        try:
            self._conn.execute("ALTER TABLE compartments ADD COLUMN stock_count INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE compartments ADD COLUMN days_of_week TEXT NOT NULL DEFAULT '[1, 2, 3, 4, 5, 6, 7]'")
        except sqlite3.OperationalError:
            pass

    def _retire_stale_events_table(self) -> None:
        """SQLite cannot alter a CHECK constraint, so a database created before an event type was
        added keeps rejecting it (IntegrityError on insert). Move such a table aside; the schema
        script then creates the current one and _restore_retired_events copies the rows back."""
        row = self._conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'events'").fetchone()
        if row is None:
            return
        required = config.SCHEMA_PATH.read_text()
        # Stale = the stored definition lacks an event type the current schema allows.
        if all(t in row["sql"] for t in _event_types(required)):
            return
        self._conn.executescript(
            """
            BEGIN;
            DROP TABLE IF EXISTS events_retired;
            ALTER TABLE events RENAME TO events_retired;
            DROP INDEX IF EXISTS idx_events_unsynced;
            DROP INDEX IF EXISTS idx_events_compartment;
            COMMIT;
            """
        )

    def _restore_retired_events(self) -> None:
        """Copies rows (including unsynced ones) from a retired table, then drops it. Also finishes
        the job if the app was closed between the two steps."""
        exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'events_retired'"
        ).fetchone()
        if exists is None:
            return
        self._conn.executescript(
            """
            BEGIN;
            INSERT OR IGNORE INTO events
                (id, event_id, compartment_id, slot_number, event_type, occurred_at, chime_count, synced, created_at)
                SELECT id, event_id, compartment_id, slot_number, event_type, occurred_at, chime_count, synced, created_at
                FROM events_retired;
            DROP TABLE events_retired;
            COMMIT;
            """
        )

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
    @_locked
    def get_compartments(self) -> list[Compartment]:
        rows = self._conn.execute(
            "SELECT * FROM compartments ORDER BY slot_number"
        ).fetchall()
        result = []
        for row in rows:
            keys = row.keys()
            days_raw = row["days_of_week"] if "days_of_week" in keys else "[1, 2, 3, 4, 5, 6, 7]"
            try:
                days = json.loads(days_raw) if isinstance(days_raw, str) else list(days_raw)
            except Exception:
                days = [1, 2, 3, 4, 5, 6, 7]
            result.append(
                Compartment(
                    id=row["id"],
                    slot_number=row["slot_number"],
                    meal_relation=row["meal_relation"],
                    meal_time=row["meal_time"],
                    schedule_time=row["schedule_time"],
                    tolerance_minutes=row["tolerance_minutes"],
                    medication_name=row["medication_name"] if "medication_name" in keys else None,
                    stock_count=row["stock_count"] if "stock_count" in keys else 0,
                    is_active=bool(row["is_active"]) if "is_active" in keys else True,
                    days_of_week=days,
                )
            )
        return result

    @_locked
    def update_stock(self, slot_number: int, delta: int) -> int:
        """Atomically increment or decrement stock_count for a slot, bounded between 0 and 30."""
        row = self._conn.execute(
            "SELECT stock_count FROM compartments WHERE slot_number = ?", (slot_number,)
        ).fetchone()
        if not row:
            return 0
        current_stock = row["stock_count"]
        new_stock = max(0, min(30, current_stock + delta))
        self._conn.execute(
            "UPDATE compartments SET stock_count = ? WHERE slot_number = ?",
            (new_stock, slot_number),
        )
        self._conn.commit()
        return new_stock

    @_locked
    def set_stock(self, slot_number: int, count: int) -> int:
        """Set stock_count directly, bounded between 0 and 30."""
        new_stock = max(0, min(30, count))
        self._conn.execute(
            "UPDATE compartments SET stock_count = ? WHERE slot_number = ?",
            (new_stock, slot_number),
        )
        self._conn.commit()
        return new_stock

    @_locked
    def update_schedules(self, schedules: list[dict]) -> None:
        self._conn.execute("UPDATE compartments SET is_active = 0")
        for s in schedules:
            sched_time = s.get("window_start") or s.get("schedule_time", "08:00")
            tolerance = s.get("tolerance_minutes", 30)
            med_name = s.get("medication_name")
            slot = s["slot_number"]
            days = s.get("days_of_week", [1, 2, 3, 4, 5, 6, 7])
            days_str = json.dumps(days) if isinstance(days, list) else str(days)
            active = 1 if s.get("active", True) else 0

            self._conn.execute(
                """UPDATE compartments 
                   SET schedule_time = ?, tolerance_minutes = ?, medication_name = ?, days_of_week = ?, is_active = ?
                   WHERE slot_number = ?""",
                (sched_time, tolerance, med_name, days_str, active, slot)
            )
        self._conn.commit()

    # -- events / telemetry buffer ----------------------------------------------
    @_locked
    def log_event(self, compartment_id: int, slot_number: int, event_type: str, occurred_at: datetime, chime_count: int = 0) -> int:
        event_id = str(uuid.uuid4())
        cur = self._conn.execute(
            "INSERT INTO events (event_id, compartment_id, slot_number, event_type, occurred_at, chime_count) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, compartment_id, slot_number, event_type, occurred_at.isoformat(), chime_count),
        )
        self._conn.commit()
        return cur.lastrowid

    @_locked
    def get_events_for_compartment_since(
        self, compartment_id: int, since: datetime
    ) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM events WHERE compartment_id = ? AND occurred_at >= ? ORDER BY occurred_at",
            (compartment_id, since.isoformat()),
        ).fetchall()

    @_locked
    def get_events_between(self, start: datetime, end: datetime) -> list[sqlite3.Row]:
        """Events with start <= occurred_at <= end, oldest first (timestamps are naive local ISO
        strings, which sort chronologically)."""
        return self._conn.execute(
            "SELECT * FROM events WHERE occurred_at >= ? AND occurred_at <= ? ORDER BY occurred_at",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    @_locked
    def get_unsynced_events(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM events WHERE synced = 0 ORDER BY occurred_at"
        ).fetchall()

    @_locked
    def mark_synced(self, db_ids: list[int]) -> None:
        if not db_ids:
            return
        placeholders = ",".join("?" for _ in db_ids)
        self._conn.execute(
            f"UPDATE events SET synced = 1 WHERE id IN ({placeholders})", db_ids
        )
        self._conn.commit()

    # -- device state -----------------------------------------------------------
    @_locked
    def get_device_state(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM device_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    @_locked
    def update_device_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO device_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        self._conn.commit()

    @_locked
    def close(self) -> None:
        self._conn.close()
