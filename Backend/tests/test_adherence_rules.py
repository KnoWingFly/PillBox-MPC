"""Pure adherence rules (no database)."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.models.enums import JournalStatus
from app.services.adherence import (
    AdherenceSummary,
    delay_minutes_for,
    dose_instants,
    journal_status,
    match_dose,
)

JKT = ZoneInfo("Asia/Jakarta")
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]


def test_dose_instants_deadline_is_window_end_plus_tolerance() -> None:
    inst = dose_instants(date(2026, 9, 28), time(7, 0), time(7, 30), 30, JKT)
    assert inst.scheduled_for == datetime(2026, 9, 28, 7, 0, tzinfo=JKT)
    assert inst.deadline_at == datetime(2026, 9, 28, 8, 0, tzinfo=JKT)


def test_on_time_within_window_has_zero_delay() -> None:
    end = datetime(2026, 9, 28, 7, 30, tzinfo=JKT)
    assert delay_minutes_for(datetime(2026, 9, 28, 7, 29, tzinfo=JKT), end) == 0
    assert delay_minutes_for(datetime(2026, 9, 28, 7, 30, 59, tzinfo=JKT), end) == 0


def test_late_delay_counts_whole_minutes_after_window_end() -> None:
    end = datetime(2026, 9, 28, 7, 30, tzinfo=JKT)
    assert delay_minutes_for(datetime(2026, 9, 28, 7, 45, 10, tzinfo=JKT), end) == 15


def test_match_dose_rejects_events_after_deadline() -> None:
    args = (time(7, 0), time(7, 30), 30, ALL_DAYS, JKT, 15)
    assert match_dose(datetime(2026, 9, 28, 7, 59, tzinfo=JKT), *args) is not None
    assert match_dose(datetime(2026, 9, 28, 8, 1, tzinfo=JKT), *args) is None
    assert match_dose(datetime(2026, 9, 28, 6, 40, tzinfo=JKT), *args) is None  # earlier than early-accept


def test_match_dose_handles_deadline_after_midnight() -> None:
    inst = match_dose(datetime(2026, 9, 29, 0, 10, tzinfo=JKT), time(23, 30), time(23, 45), 60, ALL_DAYS, JKT, 0)
    assert inst is not None and inst.scheduled_date == date(2026, 9, 28)


def test_match_dose_respects_days_of_week() -> None:
    monday_only = [1]
    tuesday = datetime(2026, 9, 29, 7, 10, tzinfo=JKT)  # 2026-09-29 is a Tuesday
    assert match_dose(tuesday, time(7, 0), time(7, 30), 30, monday_only, JKT, 0) is None


def test_summary_rates() -> None:
    s = AdherenceSummary()
    s.add("TAKEN", 0)
    s.add("TAKEN", 20)
    s.add("MISSED", None)
    s.add("PENDING", None)
    assert (s.scheduled, s.taken_on_time, s.taken_late, s.missed, s.pending) == (4, 1, 1, 1, 1)
    assert s.compliance_rate == round(100 * 2 / 3, 1)
    assert s.avg_delay_minutes == 10.0
    assert journal_status("TAKEN", 3) is JournalStatus.TAKEN_LATE
