"""Thin SQLite wrapper. Kept dependency-free (stdlib sqlite3 only) so the
core/scheduler and tests never need a running PySide6 app to exercise it.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from smart_pillbox import config
from smart_pillbox.models import Compartment, is_int, parse_hhmm

logger = logging.getLogger(__name__)

# Stored when days_of_week is missing; also the column default of old databases being migrated.
_ALL_DAYS_JSON = json.dumps(config.ISO_WEEKDAYS)

# Columns added after the first release, created on databases that predate them (one ALTER each).
_ADDED_COLUMNS = (
    ("medication_name", "TEXT NULL"),
    ("is_active", "INTEGER NOT NULL DEFAULT 1"),
    ("stock_count", f"INTEGER NOT NULL DEFAULT {config.MIN_STOCK}"),
    ("days_of_week", f"TEXT NOT NULL DEFAULT '{_ALL_DAYS_JSON}'"),
    ("window_end", "TEXT NULL"),
    ("schedule_id", "TEXT NULL"),
)


class ConfigError(ValueError):
    """A pulled config that cannot be applied as a whole. Nothing of it is stored: the device
    keeps running its previous config."""


def _hhmm(value: object, field: str, slot: object) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"slot {slot}: {field} is missing or not a string")
    try:
        parsed = parse_hhmm(value)
    except ValueError as exc:
        raise ConfigError(f"slot {slot}: {field} is not HH:MM") from exc
    return parsed.strftime(config.SCHEDULE_TIME_FORMAT)


def validate_schedules(schedules: object) -> list[dict]:
    """Checks every schedule of a pulled config (contract §2.2) and returns normalized rows.
    Raises ConfigError on the first problem, so a partial config is never half applied."""
    if not isinstance(schedules, list):
        raise ConfigError("schedules is not a list")
    rows: list[dict] = []
    seen: set[int] = set()
    for index, item in enumerate(schedules):
        if not isinstance(item, dict):
            raise ConfigError(f"schedule #{index} is not an object")
        slot = item.get("slot_number")
        if not is_int(slot) or slot not in config.SLOT_NUMBERS:
            raise ConfigError(f"schedule #{index}: slot_number must be one of {config.SLOT_NUMBERS.start}-{config.SLOT_NUMBERS.stop - 1}")
        if slot in seen:
            raise ConfigError(f"slot {slot} appears more than once")
        seen.add(slot)
        window_end = item.get("window_end")
        tolerance = item.get("tolerance_minutes", config.DEFAULT_TOLERANCE_MINUTES)
        if not is_int(tolerance) or tolerance < 0:
            raise ConfigError(f"slot {slot}: tolerance_minutes must be an integer >= 0")
        days = item.get("days_of_week", config.ISO_WEEKDAYS)
        if not isinstance(days, list) or not all(is_int(d) and d in config.ISO_WEEKDAYS for d in days):
            raise ConfigError(f"slot {slot}: days_of_week must list ISO weekdays")
        active = item.get("active", True)
        if not isinstance(active, bool):
            raise ConfigError(f"slot {slot}: active must be true or false")
        medication = item.get("medication_name")
        schedule_id = item.get("schedule_id")
        for field, value in (("medication_name", medication), ("schedule_id", schedule_id)):
            if value is not None and not isinstance(value, str):
                raise ConfigError(f"slot {slot}: {field} must be a string")
        rows.append(
            {
                "slot_number": slot,
                "schedule_time": _hhmm(item.get("window_start"), "window_start", slot),
                "window_end": None if window_end is None else _hhmm(window_end, "window_end", slot),
                "tolerance_minutes": tolerance,
                "days_of_week": json.dumps(sorted(set(days))),
                "is_active": int(active),
                "medication_name": medication,
                "schedule_id": schedule_id,
            }
        )
    return rows


def backup_corrupt_database(db_path: str | Path, now: datetime | None = None) -> Path:
    """Moves a database that cannot be opened (and its WAL files) aside, so a fresh one can be
    created in its place. Returns the backup path."""
    path = Path(db_path)
    stamp = (now or datetime.now()).strftime(config.CORRUPT_DB_TIMESTAMP_FORMAT)
    backup = path.with_name(f"{path.name}{config.CORRUPT_DB_SUFFIX}{stamp}")
    for suffix in ("", "-wal", "-shm"):
        source = path.with_name(path.name + suffix)
        if source.exists():
            source.rename(backup.with_name(backup.name + suffix))
    logger.warning("Corrupt database moved to %s.", backup)
    return backup


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
        try:
            self._configure_connection()
            self._init_schema()
            self._seed_default_compartments_if_empty()
        except sqlite3.DatabaseError:
            # Not a database, or damaged: the caller may back it up and start fresh (backup_corrupt_database).
            self._conn.close()
            raise

    # -- setup ---------------------------------------------------------------
    def _configure_connection(self) -> None:
        # The first statements that read the file: a damaged database fails here, not mid-demo.
        check = self._conn.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise sqlite3.DatabaseError(f"quick_check failed: {check}")
        self._conn.execute(f"PRAGMA journal_mode={config.SQLITE_JOURNAL_MODE}")
        self._conn.execute(f"PRAGMA synchronous={config.SQLITE_SYNCHRONOUS}")

    def _init_schema(self) -> None:
        sql = config.SCHEMA_PATH.read_text()
        self._retire_stale_events_table()
        self._conn.executescript(sql)
        self._restore_retired_events()
        self._conn.commit()
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """Brings a database created by an older version up to the current compartments table.
        Each ALTER runs on its own, so one failure does not skip the columns after it."""
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(compartments)")}
        for name, ddl in _ADDED_COLUMNS:
            if name in existing:
                continue
            try:
                self._conn.execute(f"ALTER TABLE compartments ADD COLUMN {name} {ddl}")
                self._conn.commit()
            except sqlite3.OperationalError:
                logger.exception("Could not add column compartments.%s.", name)

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
            try:
                days = json.loads(row["days_of_week"])
            except (TypeError, ValueError):
                days = None
            if not isinstance(days, list) or not all(is_int(d) for d in days):
                logger.warning("Slot %s has unreadable days_of_week; using every day.", row["slot_number"])
                days = list(config.ISO_WEEKDAYS)
            result.append(
                Compartment(
                    id=row["id"],
                    slot_number=row["slot_number"],
                    meal_relation=row["meal_relation"],
                    meal_time=row["meal_time"],
                    schedule_time=row["schedule_time"],
                    tolerance_minutes=row["tolerance_minutes"],
                    medication_name=row["medication_name"],
                    stock_count=row["stock_count"],
                    is_active=bool(row["is_active"]),
                    days_of_week=days,
                    window_end=row["window_end"],
                    schedule_id=row["schedule_id"],
                )
            )
        return result

    @_locked
    def update_stock(self, slot_number: int, delta: int) -> int:
        """Atomically increment or decrement stock_count for a slot, bounded by MIN_STOCK..MAX_STOCK_CAPACITY."""
        row = self._conn.execute(
            "SELECT stock_count FROM compartments WHERE slot_number = ?", (slot_number,)
        ).fetchone()
        if not row:
            return 0
        current_stock = row["stock_count"]
        new_stock = max(config.MIN_STOCK, min(config.MAX_STOCK_CAPACITY, current_stock + delta))
        self._conn.execute(
            "UPDATE compartments SET stock_count = ? WHERE slot_number = ?",
            (new_stock, slot_number),
        )
        self._conn.commit()
        return new_stock

    @_locked
    def set_stock(self, slot_number: int, count: int) -> int:
        """Set stock_count directly, bounded by MIN_STOCK..MAX_STOCK_CAPACITY."""
        new_stock = max(config.MIN_STOCK, min(config.MAX_STOCK_CAPACITY, count))
        self._conn.execute(
            "UPDATE compartments SET stock_count = ? WHERE slot_number = ?",
            (new_stock, slot_number),
        )
        self._conn.commit()
        return new_stock

    @_locked
    def apply_config(self, schedules: object, device_state: dict[str, str] | None = None) -> None:
        """Applies a pulled config in one transaction: every schedule (a slot missing from the list
        has no schedule, contract §2.2) plus the given device_state keys, or nothing at all.
        Raises ConfigError, before touching the database, when any schedule is invalid."""
        rows = validate_schedules(schedules)
        with self._conn:  # commits, or rolls back on any error
            self._conn.execute("UPDATE compartments SET is_active = 0")
            self._conn.executemany(
                """UPDATE compartments
                   SET schedule_time = :schedule_time, window_end = :window_end,
                       tolerance_minutes = :tolerance_minutes, medication_name = :medication_name,
                       days_of_week = :days_of_week, is_active = :is_active, schedule_id = :schedule_id
                   WHERE slot_number = :slot_number""",
                rows,
            )
            self._upsert_device_state(device_state or {})

    def update_schedules(self, schedules: object) -> None:
        self.apply_config(schedules)

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
    def get_unsynced_events(self, limit: int | None = None) -> list[sqlite3.Row]:
        """Unsynced events, oldest first; `limit` reads one outbox chunk without loading the rest."""
        if limit is None:
            return self._conn.execute("SELECT * FROM events WHERE synced = 0 ORDER BY occurred_at").fetchall()
        return self._conn.execute(
            "SELECT * FROM events WHERE synced = 0 ORDER BY occurred_at LIMIT ?", (limit,)
        ).fetchall()

    @_locked
    def count_unsynced_events(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM events WHERE synced = 0").fetchone()[0]

    @_locked
    def delete_unsynced_events(self) -> int:
        """Drops the outbox (identity reset: those events belong to a device the server forgot)."""
        with self._conn:
            return self._conn.execute("DELETE FROM events WHERE synced = 0").rowcount

    @_locked
    def prune_synced_events(self, before: datetime) -> int:
        """Deletes synced events that occurred before `before`; unsynced ones are always kept."""
        with self._conn:
            return self._conn.execute(
                "DELETE FROM events WHERE synced = 1 AND occurred_at < ?", (before.isoformat(),)
            ).rowcount

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
    def get_device_states(self, keys: tuple[str, ...]) -> dict[str, str | None]:
        """Several device_state keys in one query; a missing key maps to None."""
        placeholders = ",".join("?" for _ in keys)
        rows = self._conn.execute(
            f"SELECT key, value FROM device_state WHERE key IN ({placeholders})", keys
        ).fetchall()
        found = {row["key"]: row["value"] for row in rows}
        return {key: found.get(key) for key in keys}

    @_locked
    def update_device_state(self, key: str, value: str) -> None:
        self.update_device_states({key: value})

    @_locked
    def update_device_states(self, values: dict[str, str]) -> None:
        """Writes several device_state keys in one transaction."""
        with self._conn:
            self._upsert_device_state(values)

    def _upsert_device_state(self, values: dict[str, str]) -> None:
        self._conn.executemany(
            "INSERT INTO device_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            list(values.items()),
        )

    @_locked
    def close(self) -> None:
        self._conn.close()
