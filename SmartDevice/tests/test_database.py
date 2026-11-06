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

    event_id = db.log_event(compartment_id, 1, "POPUP_ACTIVATED", now)
    unsynced = db.get_unsynced_events()
    assert len(unsynced) == 1
    assert unsynced[0]["id"] == event_id
    assert unsynced[0]["synced"] == 0

    db.mark_synced([event_id])
    assert db.get_unsynced_events() == []


def test_update_schedules_applies_a_pulled_config(tmp_path):
    db = make_db(tmp_path)
    compartment = db.get_compartments()[0]
    db.update_schedules([
        {"slot_number": compartment.slot_number, "window_start": "08:15", "window_end": "08:15", "tolerance_minutes": 45},
    ])
    compartments = {c.id: c for c in db.get_compartments()}
    updated = compartments[compartment.id]
    assert updated.schedule_time == "08:15"
    assert updated.tolerance_minutes == 45
    # A slot missing from the config has no schedule (contract §2.2).
    assert all(not c.is_active for c in compartments.values() if c.id != compartment.id)


def test_unsynced_events_are_read_oldest_first_in_chunks(tmp_path):
    db = make_db(tmp_path)
    compartment_id = db.get_compartments()[0].id
    base = datetime(2026, 1, 1, 7, 0, 0)
    for minute in (3, 1, 2):
        db.log_event(compartment_id, 1, "REFILL_MAINTENANCE", base.replace(minute=minute))
    first_two = db.get_unsynced_events(limit=2)
    assert [row["occurred_at"] for row in first_two] == [base.replace(minute=1).isoformat(), base.replace(minute=2).isoformat()]


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
    assert {"idx_events_outbox", "idx_events_compartment", "idx_events_occurred"} <= indexes
    assert "idx_events_unsynced" not in indexes  # duplicate of idx_events_outbox's prefix
    # Opening again must not migrate (or break) anything.
    Database(db_path=db_path)


def test_gui_and_sync_threads_can_share_the_connection(tmp_path):
    """The GUI tick and the sync worker run the same queries at the same time; on one shared
    connection that used to fail with "InterfaceError: bad parameter or other API misuse"."""
    import threading

    db = make_db(tmp_path)
    errors = []

    def poll():
        for _ in range(3000):
            try:
                db.get_device_state("device_code")
                db.get_compartments()
            except Exception as exc:  # noqa: BLE001 - collected for the assert
                errors.append(exc)

    threads = [threading.Thread(target=poll) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# --- config validation, tuning and recovery --------------------------------------------

import sqlite3  # noqa: E402

import pytest  # noqa: E402

from smart_pillbox.db.database import ConfigError, backup_corrupt_database  # noqa: E402

GOOD = {"slot_number": 1, "window_start": "08:15", "window_end": "08:30", "tolerance_minutes": 45,
        "days_of_week": [1, 3, 5], "active": True, "schedule_id": "abc", "medication_name": "Obat"}


def _snapshot(db):
    return [(c.slot_number, c.schedule_time, c.window_end, c.tolerance_minutes, c.is_active, c.days_of_week)
            for c in db.get_compartments()]


@pytest.mark.parametrize(
    "schedules",
    [
        [GOOD, {**GOOD, "slot_number": 2, "window_start": "8.15"}],
        [GOOD, {**GOOD, "slot_number": 2, "window_end": "24:00"}],
        [GOOD, {**GOOD, "slot_number": 0}],
        [GOOD, {**GOOD, "slot_number": True}],
        [GOOD, {**GOOD, "slot_number": 2, "tolerance_minutes": "30"}],
        [GOOD, {**GOOD, "slot_number": 2, "days_of_week": [0, 8]}],
        [GOOD, {**GOOD, "slot_number": 2, "active": "yes"}],
        [GOOD, {**GOOD, "slot_number": 2, "medication_name": 5}],
        [GOOD, GOOD],
        [GOOD, "not an object"],
        {"slot_number": 1},
    ],
)
def test_bad_or_partial_config_keeps_the_old_schedules(tmp_path, schedules):
    db = make_db(tmp_path)
    before = _snapshot(db)
    with pytest.raises(ConfigError):
        db.update_schedules(schedules)
    assert _snapshot(db) == before


def test_config_transaction_rolls_back_on_a_database_error(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    before = _snapshot(db)
    db._conn.execute("CREATE TRIGGER fail_slot_2 BEFORE UPDATE ON compartments WHEN NEW.slot_number = 2 "
                     "AND NEW.is_active = 1 BEGIN SELECT RAISE(ABORT, 'boom'); END")
    with pytest.raises(sqlite3.DatabaseError):
        db.apply_config([GOOD, {**GOOD, "slot_number": 2}], {"config_version": "5"})
    assert _snapshot(db) == before
    assert db.get_device_state("config_version") == "1"


def test_window_end_and_schedule_id_are_stored(tmp_path):
    db = make_db(tmp_path)
    db.update_schedules([GOOD])
    slot1 = next(c for c in db.get_compartments() if c.slot_number == 1)
    assert (slot1.window_end, slot1.schedule_id, slot1.days_of_week) == ("08:30", "abc", [1, 3, 5])


def test_wal_mode_is_used(tmp_path):
    db = make_db(tmp_path)
    assert db._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_pruning_keeps_unsynced_events(tmp_path):
    db = make_db(tmp_path)
    compartment_id = db.get_compartments()[0].id
    old = datetime(2025, 1, 1, 7, 0)
    synced = db.log_event(compartment_id, 1, "POPUP_ACTIVATED", old)
    db.log_event(compartment_id, 1, "COMPARTMENT_OPENED", old)
    db.mark_synced([synced])
    assert db.prune_synced_events(datetime(2026, 1, 1)) == 1
    assert [r["event_type"] for r in db.get_unsynced_events()] == ["COMPARTMENT_OPENED"]
    assert db.count_unsynced_events() == 1


def test_corrupt_database_can_be_backed_up_and_recreated(tmp_path):
    path = tmp_path / "broken.db"
    path.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        Database(db_path=path)
    backup = backup_corrupt_database(path, now=datetime(2026, 11, 3, 9, 0))
    assert backup.exists() and not path.exists()
    assert len(Database(db_path=path).get_compartments()) == 8


def test_old_database_without_new_columns_is_migrated(tmp_path):
    path = tmp_path / "v0.db"
    raw = sqlite3.connect(path)
    raw.execute("""CREATE TABLE compartments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, slot_number INTEGER NOT NULL UNIQUE,
        meal_relation TEXT NOT NULL, meal_time TEXT NOT NULL, schedule_time TEXT NOT NULL,
        tolerance_minutes INTEGER NOT NULL DEFAULT 30)""")
    raw.execute("INSERT INTO compartments (slot_number, meal_relation, meal_time, schedule_time) "
                "VALUES (1, 'sebelum_makan', 'pagi', '07:00')")
    raw.commit()
    raw.close()
    compartment = Database(db_path=path).get_compartments()[0]
    assert compartment.is_active and compartment.days_of_week == [1, 2, 3, 4, 5, 6, 7]
    assert compartment.window_end is None and compartment.schedule_id is None
