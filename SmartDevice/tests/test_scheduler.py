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


def test_opening_a_chamber_that_is_not_active_is_an_unscheduled_open(tmp_path):
    """SmartDevice/CLAUDE.md: opening any chamber that is not the ACTIVE one logs UNSCHEDULED_OPEN
    (the backend raises a critical alert); the chamber's dose state does not change."""
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 0))
    compartment = next(iter(scheduler.compartments.values()))

    scheduler.interact(compartment.id)  # never activated

    assert compartment.state == ChamberState.IDLE
    events = scheduler.db.get_unsynced_events()
    assert [(e["event_type"], e["slot_number"]) for e in events] == [("UNSCHEDULED_OPEN", compartment.slot_number)]


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


def _only_slot_one(scheduler, schedule_time="08:00", tolerance=30):
    compartment = next(c for c in scheduler.compartments.values() if c.slot_number == 1)
    compartment.schedule_time = schedule_time
    compartment.tolerance_minutes = tolerance
    compartment.is_active = True
    scheduler.restore_day()  # as after a config pull: judge today with this schedule
    return compartment


def test_start_after_window_closed_marks_missed_without_popping(tmp_path):
    # The simulator is opened at 18:00; the 08:00 dose must not pop up ten hours late.
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 18, 0))
    compartment = _only_slot_one(scheduler)

    scheduler.tick()

    assert compartment.state == ChamberState.MISSED
    assert scheduler.active_chamber_id is None
    assert scheduler.db.get_unsynced_events() == []  # never rang, so no ALARM_TIMEOUT


def test_start_inside_window_still_pops_up(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 8, 10))
    compartment = _only_slot_one(scheduler)

    scheduler.tick()

    assert compartment.state == ChamberState.ACTIVE


def test_late_pop_up_times_out_at_the_schedule_deadline(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 8, 20))
    compartment = _only_slot_one(scheduler, tolerance=30)
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE

    scheduler.clock.set_time(datetime(2026, 1, 1, 8, 31))  # 08:00 + 30, not 08:20 + 30
    scheduler.tick()

    assert compartment.state == ChamberState.MISSED
    timeout = scheduler.db.get_unsynced_events()[-1]
    assert timeout["event_type"] == "ALARM_TIMEOUT"
    assert timeout["occurred_at"] == datetime(2026, 1, 1, 8, 30).isoformat()


def test_restart_restores_a_dose_taken_earlier_today(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 8, 1))
    compartment = _only_slot_one(scheduler)
    scheduler.tick()
    scheduler.interact(compartment.id)
    assert compartment.state == ChamberState.TAKEN

    # Same database, new process, still inside the window.
    restarted = PillboxScheduler(scheduler.db, SimulatedClock(start_at=datetime(2026, 1, 1, 8, 5)))
    again = _only_slot_one(restarted)
    restarted.tick()

    assert again.state == ChamberState.TAKEN
    assert restarted.active_chamber_id is None


def test_new_day_rearms_yesterdays_taken_dose(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 8, 1))
    compartment = _only_slot_one(scheduler)
    scheduler.tick()
    scheduler.interact(compartment.id)

    scheduler.clock.set_time(datetime(2026, 1, 2, 7, 59))
    scheduler.tick()
    assert compartment.state == ChamberState.IDLE

    scheduler.clock.set_time(datetime(2026, 1, 2, 8, 0, 5))
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE


def test_schedule_added_after_its_window_waits_for_tomorrow(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 18, 0))
    compartment = next(c for c in scheduler.compartments.values() if c.slot_number == 4)
    compartment.is_active = False

    scheduler.db.update_schedules([{"slot_number": 4, "window_start": "10:40", "tolerance_minutes": 30}])
    scheduler.reload_schedules()
    scheduler.tick()

    assert compartment.state == ChamberState.IDLE  # not an instant "missed"
    assert scheduler.active_chamber_id is None


def test_next_due_at_skips_to_tomorrow_when_today_is_done(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 18, 0))
    for other in scheduler.compartments.values():
        other.is_active = False
    _only_slot_one(scheduler)
    scheduler.tick()

    assert scheduler.next_due_at() == datetime(2026, 1, 2, 8, 0)


def test_release_late_reopens_a_missed_dose_until_the_given_time(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 9, 0))
    compartment = _only_slot_one(scheduler)  # 08:00 + 30: missed
    assert compartment.state == ChamberState.MISSED

    assert scheduler.release_late(1, datetime(2026, 1, 1, 9, 15)) is None
    assert compartment.state == ChamberState.ACTIVE
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE  # its own deadline no longer applies

    scheduler.interact(compartment.id)
    assert compartment.state == ChamberState.TAKEN
    assert scheduler.db.get_unsynced_events()[-1]["event_type"] == "COMPARTMENT_OPENED"


def test_release_late_expires(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 9, 0))
    compartment = _only_slot_one(scheduler)
    scheduler.release_late(1, datetime(2026, 1, 1, 9, 15))

    scheduler.clock.set_time(datetime(2026, 1, 1, 9, 16))
    scheduler.tick()

    assert compartment.state == ChamberState.MISSED
    assert scheduler.active_chamber_id is None


def test_release_late_refuses_while_another_chamber_is_active(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 9, 0))
    _only_slot_one(scheduler)
    other = next(c for c in scheduler.compartments.values() if c.slot_number == 2)
    other.schedule_time, other.is_active = "08:55", True
    scheduler.tick()
    assert scheduler.active_chamber_id == other.id

    assert scheduler.release_late(1, datetime(2026, 1, 1, 9, 15)) is not None


def test_opening_after_the_clock_moved_back_logs_no_negative_chime_count(tmp_path):
    """The backend rejects chime_count < 0; it used to go negative when the RTC was set back
    while a chamber was up (time_sync, "Sync Jam Nyata")."""
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 59))
    compartment = next(iter(scheduler.compartments.values()))
    compartment.schedule_time = "07:00"
    scheduler.clock.jump(timedelta(minutes=2))
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE

    scheduler.clock.jump(timedelta(minutes=-1))
    scheduler.interact(compartment.id)

    opened = [e for e in scheduler.db.get_unsynced_events() if e["event_type"] == "COMPARTMENT_OPENED"]
    assert opened and opened[-1]["chime_count"] == 0


# --- robustness (config, restarts, midnight) ----------------------------------------

def test_deadline_after_midnight_does_not_skip_the_next_day(tmp_path):
    """A 23:50 dose with 30 min tolerance times out at 00:20 the next day. It used to be recorded
    as done for the NEW day, so that day's 23:50 dose never popped up."""
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 23, 49))
    compartment = next(iter(scheduler.compartments.values()))
    compartment.schedule_time = "23:50"
    compartment.tolerance_minutes = 30
    scheduler.restore_day()  # started at 23:49: forget the seeded 07:00 dose that is already over

    scheduler.clock.jump(timedelta(minutes=2))  # 23:51 day 1
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE

    scheduler.clock.jump(timedelta(minutes=30))  # 00:21 day 2: past the deadline
    scheduler.tick()
    assert compartment.state == ChamberState.MISSED

    scheduler.clock.set_time(datetime(2026, 1, 2, 23, 51))  # same day 2, its own dose is due
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE
    assert compartment.due_at == datetime(2026, 1, 2, 23, 50)


def test_dose_taken_after_midnight_does_not_skip_the_next_day(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 23, 49))
    compartment = next(iter(scheduler.compartments.values()))
    compartment.schedule_time = "23:50"
    compartment.tolerance_minutes = 30
    scheduler.restore_day()  # started at 23:49: forget the seeded 07:00 dose that is already over

    scheduler.clock.jump(timedelta(minutes=2))
    scheduler.tick()
    scheduler.clock.jump(timedelta(minutes=15))  # 00:06 day 2, still inside the window
    scheduler.tick()
    scheduler.open_compartment(compartment.id)
    scheduler.close_compartment(compartment.id)
    assert compartment.state == ChamberState.TAKEN

    scheduler.clock.set_time(datetime(2026, 1, 2, 23, 51))
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE


def test_refill_mode_survives_a_restart(tmp_path):
    db = Database(db_path=tmp_path / "refill.db")
    first = PillboxScheduler(db, SimulatedClock(start_at=datetime(2026, 1, 1, 6, 0)))
    first.set_refill_mode(True)

    restarted = PillboxScheduler(Database(db_path=tmp_path / "refill.db"), SimulatedClock(start_at=datetime(2026, 1, 1, 6, 0)))
    assert restarted.is_refill_mode is True
    compartment = next(iter(restarted.compartments.values()))
    restarted.open_compartment(compartment.id)
    events = [row["event_type"] for row in restarted.db.get_unsynced_events()]
    assert events == ["REFILL_MAINTENANCE"]  # not UNSCHEDULED_OPEN (a critical alert)


def test_one_unreadable_slot_does_not_stop_the_others(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 59))
    broken, healthy = list(scheduler.compartments.values())[:2]
    broken.schedule_time = "7 pagi"
    healthy.schedule_time = "07:00"

    scheduler.clock.jump(timedelta(minutes=2))
    scheduler.tick()  # used to raise ValueError and stop every slot
    scheduler.restore_day()
    scheduler.reset_day()
    scheduler.tick()

    assert healthy.state == ChamberState.ACTIVE
    assert broken.state == ChamberState.IDLE
    assert scheduler.get_next_dose() is None or scheduler.get_next_dose() is not broken
    assert scheduler.next_due_at() is None or isinstance(scheduler.next_due_at(), datetime)


def test_deadline_follows_window_end(tmp_path):
    """The backend's deadline is window_end + tolerance (contract §5); the device used window_start."""
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 1, 6, 59))
    compartment = next(iter(scheduler.compartments.values()))
    compartment.schedule_time = "07:00"
    compartment.window_end = "07:30"
    compartment.tolerance_minutes = 10

    scheduler.clock.jump(timedelta(minutes=2))
    scheduler.tick()
    scheduler.clock.set_time(datetime(2026, 1, 1, 7, 35))  # past start + tolerance, before end + tolerance
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE

    scheduler.clock.set_time(datetime(2026, 1, 1, 7, 41))
    scheduler.tick()
    assert compartment.state == ChamberState.MISSED


def test_released_dose_of_yesterday_does_not_block_today(tmp_path):
    scheduler = make_scheduler(tmp_path, datetime(2026, 1, 2, 6, 0))
    compartment = next(iter(scheduler.compartments.values()))
    compartment.schedule_time = "07:00"
    refused = scheduler.release_late(
        compartment.slot_number, until=datetime(2026, 1, 2, 6, 30), scheduled_for=datetime(2026, 1, 1, 22, 0)
    )
    assert refused is None
    scheduler.open_compartment(compartment.id)
    scheduler.close_compartment(compartment.id)

    scheduler.clock.set_time(datetime(2026, 1, 2, 7, 1))
    scheduler.tick()
    assert compartment.state == ChamberState.ACTIVE
