from datetime import datetime

from smart_pillbox.db.database import Database


def make_db(tmp_path):
    return Database(db_path=tmp_path / "test.db")


def test_seeds_eight_default_compartments(tmp_path):
    db = make_db(tmp_path)
    compartments = db.get_compartments()
    assert len(compartments) == 8
    relations = {c.meal_relation for c in compartments}
    times = {c.meal_time for c in compartments}
    assert relations == {"sebelum_makan", "sesudah_makan"}
    assert times == {"pagi", "siang", "sore", "malam"}


def test_seeding_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    Database(db_path=db_path)
    db2 = Database(db_path=db_path)  # reopening must not duplicate rows
    assert len(db2.get_compartments()) == 8


def test_log_event_and_sync_cycle(tmp_path):
    db = make_db(tmp_path)
    compartment_id = db.get_compartments()[0].id
    now = datetime(2026, 1, 1, 7, 0, 0)

    event_id = db.log_event(compartment_id, "POP_UP", now)
    unsynced = db.get_unsynced_events()
    assert len(unsynced) == 1
    assert unsynced[0]["id"] == event_id
    assert unsynced[0]["synced"] == 0

    db.mark_synced([event_id])
    assert db.get_unsynced_events() == []


def test_update_schedule(tmp_path):
    db = make_db(tmp_path)
    compartment = db.get_compartments()[0]
    db.update_schedule(compartment.id, "08:15", 45)
    updated = next(c for c in db.get_compartments() if c.id == compartment.id)
    assert updated.schedule_time == "08:15"
    assert updated.tolerance_minutes == 45


CONTRACT_EVENT_TYPES = [
    "POPUP_ACTIVATED", "COMPARTMENT_OPENED", "COMPARTMENT_CLOSED", "ALARM_TIMEOUT",
    "UNSCHEDULED_OPEN", "REFILL_MAINTENANCE", "ALARM_STARTED", "ALARM_STOPPED",
    "BATTERY_STATUS", "NETWORK_RECOVERED",
]


def test_every_backend_contract_event_type_can_be_logged(tmp_path):
    db = make_db(tmp_path)
    compartment = db.get_compartments()[0]
    now = datetime(2026, 1, 1, 7, 0, 0)
    for event_type in CONTRACT_EVENT_TYPES:
        db.log_event(compartment.id, compartment.slot_number, event_type, now)
    assert len(db.get_unsynced_events()) == len(CONTRACT_EVENT_TYPES)


def test_unknown_event_type_is_still_rejected(tmp_path):
    import sqlite3

    import pytest

    db = make_db(tmp_path)
    compartment = db.get_compartments()[0]
    with pytest.raises(sqlite3.IntegrityError):
        db.log_event(compartment.id, compartment.slot_number, "NOT_A_REAL_EVENT", datetime(2026, 1, 1))


def test_old_database_is_migrated_and_keeps_its_events(tmp_path):
    import pytest

    """A pillbox_local.db created before ALARM_STARTED existed must accept it after opening,
    and must not lose events that were still waiting to sync."""
    import sqlite3

    db_path = tmp_path / "old.db"
    db = Database(db_path=db_path)
    compartment = db.get_compartments()[0]
    db.log_event(compartment.id, compartment.slot_number, "COMPARTMENT_OPENED", datetime(2026, 1, 1, 7, 0))
    synced_id = db.log_event(compartment.id, compartment.slot_number, "POPUP_ACTIVATED", datetime(2026, 1, 1, 6, 59))
    db.mark_synced([synced_id])
    db._conn.close()

    # Recreate the old table definition (the constraint without the contract-only types).
    raw = sqlite3.connect(db_path)
    rows = raw.execute("SELECT * FROM events").fetchall()
    raw.executescript(
        """
        DROP TABLE events;
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            compartment_id INTEGER REFERENCES compartments (id),
            slot_number INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'POPUP_ACTIVATED', 'COMPARTMENT_OPENED', 'COMPARTMENT_CLOSED',
                'ALARM_TIMEOUT', 'UNSCHEDULED_OPEN', 'REFILL_MAINTENANCE')),
            occurred_at TEXT NOT NULL,
            chime_count INTEGER NOT NULL DEFAULT 0,
            synced INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_events_unsynced ON events (synced);
        """
    )
    raw.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)", rows)
    raw.commit()
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "INSERT INTO events (event_id, slot_number, event_type, occurred_at) VALUES ('x', 1, 'ALARM_STARTED', 'now')"
        )
    raw.close()

    migrated = Database(db_path=db_path)  # opening runs the migration
    migrated.log_event(compartment.id, compartment.slot_number, "ALARM_STARTED", datetime(2026, 1, 1, 8, 0))
    unsynced = {r["event_type"] for r in migrated.get_unsynced_events()}
    assert unsynced == {"COMPARTMENT_OPENED", "ALARM_STARTED"}
    total = migrated._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert total == 3  # nothing lost, including the already-synced row
    leftovers = migrated._conn.execute(
        "SELECT name FROM sqlite_master WHERE name IN ('events_retired')"
    ).fetchall()
    assert leftovers == []
    indexes = {r[0] for r in migrated._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_events_unsynced", "idx_events_compartment"} <= indexes
    # Opening again must not migrate (or break) anything.
    Database(db_path=db_path)
