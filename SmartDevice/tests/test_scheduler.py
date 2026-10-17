from datetime import datetime, timedelta

from smart_pillbox.core.rtc import SimulatedClock
from smart_pillbox.core.scheduler import PillboxScheduler
from smart_pillbox.db.database import Database
from smart_pillbox.models import ChamberState


def make_scheduler(tmp_path, start_at: datetime) -> PillboxScheduler:
    db = Database(db_path=tmp_path / "test.db")
    clock = SimulatedClock(start_at=start_at, speed=1.0)
    scheduler = PillboxScheduler(db, clock)

    # Neutralize the seeded default schedule so only the times a test
    # explicitly sets can become due — otherwise a default (e.g. another
    # compartment also defaulting to "07:00") can coincidentally collide
    # and grab the freed active slot right after a test's own MISSED/TAKEN,
    # making the test flaky-by-coincidence rather than deterministic.
    for compartment in scheduler.compartments.values():
        compartment.schedule_time = "23:59"

    return scheduler


def test_compartment_stays_idle_before_schedule_time(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 59))
    compartment = next(iter(scheduler.compartments.values()))
    compartment.schedule_time = "07:00"

    scheduler.tick()

    assert compartment.state == ChamberState.IDLE
    assert scheduler.active_chamber_id is None


def test_compartment_activates_when_due(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 59))
    compartment = next(iter(scheduler.compartments.values()))
    compartment.schedule_time = "07:00"

    scheduler.clock.jump(timedelta(minutes=2))  # now ~07:01
    scheduler.tick()

    assert compartment.state == ChamberState.ACTIVE
    assert scheduler.active_chamber_id == compartment.id
    assert compartment.activated_at is not None


def test_single_active_chamber_queues_second_compartment(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 59))
    compartments = list(scheduler.compartments.values())
    first, second = compartments[0], compartments[1]
    first.schedule_time = second.schedule_time = "07:00"
    first.tolerance_minutes = second.tolerance_minutes = 30

    scheduler.clock.jump(timedelta(minutes=2))
    scheduler.tick()

    active_states = [c.state for c in (first, second)]
    assert active_states.count(ChamberState.ACTIVE) == 1  # only one, per Batasan Sistem
    assert active_states.count(ChamberState.IDLE) == 1

    active_one = first if first.state == ChamberState.ACTIVE else second
    waiting_one = second if active_one is first else first

    scheduler.interact(active_one.id)
    assert active_one.state == ChamberState.TAKEN
    assert scheduler.active_chamber_id is None

    scheduler.tick()  # the queued compartment should now get its turn
    assert waiting_one.state == ChamberState.ACTIVE


def test_missed_after_tolerance_window_expires(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 59))
    compartment = next(iter(scheduler.compartments.values()))
    compartment.schedule_time = "07:00"
    compartment.tolerance_minutes = 10

    scheduler.clock.jump(timedelta(minutes=2))
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE

    scheduler.clock.jump(timedelta(minutes=11))
    scheduler.tick()

    assert compartment.state == ChamberState.MISSED
    assert scheduler.active_chamber_id is None


def test_interact_ignored_when_not_active(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 0))
    compartment = next(iter(scheduler.compartments.values()))

    scheduler.interact(compartment.id)  # never activated

    assert compartment.state == ChamberState.IDLE
    assert scheduler.db.get_unsynced_events() == []


def _take_slot_one_at_seven(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 59))
    compartment = next(c for c in scheduler.compartments.values() if c.slot_number == 1)
    compartment.schedule_time = "07:00"  # same as the seeded DB row for slot 1
    scheduler.clock.jump(timedelta(minutes=2))
    scheduler.tick()
    scheduler.interact(compartment.id)
    assert compartment.state == ChamberState.TAKEN
    return scheduler, compartment


def test_reload_rearms_a_taken_slot_whose_time_changed(tmp_path):
    scheduler, compartment = _take_slot_one_at_seven(tmp_path)

    # The caregiver moves the dose to 07:30 in the app; the device pulls the config.
    scheduler.db.update_schedules([{"slot_number": 1, "window_start": "07:30", "tolerance_minutes": 30}])
    scheduler.reload_schedules()
    assert compartment.state == ChamberState.IDLE

    scheduler.clock.jump(timedelta(minutes=30))  # ~07:31
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE


def test_reload_keeps_state_when_timing_is_unchanged(tmp_path):
    scheduler, compartment = _take_slot_one_at_seven(tmp_path)

    scheduler.db.update_schedules([{"slot_number": 1, "window_start": "07:00", "tolerance_minutes": 30}])
    scheduler.reload_schedules()
    scheduler.tick()
    assert compartment.state == ChamberState.TAKEN  # no second pop-up for the same dose
