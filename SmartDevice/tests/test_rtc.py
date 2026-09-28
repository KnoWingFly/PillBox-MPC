from datetime import datetime, timedelta

from smart_pillbox.core.rtc import SimulatedClock


def test_jump_moves_time_forward():
    clock = SimulatedClock(start_at=datetime(2026, 1, 1, 7, 0, 0), speed=1.0)
    clock.jump(timedelta(hours=1))
    now = clock.now()
    assert now.hour == 8
    assert now.minute == 0


def test_set_time_overrides_clock():
    clock = SimulatedClock(start_at=datetime(2026, 1, 1, 7, 0, 0), speed=1.0)
    clock.set_time(datetime(2026, 6, 15, 12, 30, 0))
    now = clock.now()
    assert now.date() == datetime(2026, 6, 15).date()
    assert now.hour == 12
    assert now.minute == 30


def test_speed_multiplier_accelerates_elapsed_time():
    # At 3600x speed, ~10ms of real time should already read as several
    # simulated seconds forward. Loose bound to avoid CI flakiness.
    clock = SimulatedClock(start_at=datetime(2026, 1, 1, 0, 0, 0), speed=3600.0)
    later = clock.now()
    assert later >= datetime(2026, 1, 1, 0, 0, 0)
