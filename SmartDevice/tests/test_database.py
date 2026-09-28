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
