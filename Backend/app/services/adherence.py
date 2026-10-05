"""Adherence rules (pure functions, no I/O).

Dose timeline for a schedule on local date D (device timezone):

    scheduled_for = D @ window_start
    window_end_at = D @ window_end
    deadline_at   = window_end_at + tolerance_minutes

- taken at t <= window_end_at                 -> TAKEN, delay_minutes = 0 (on time)
- window_end_at < t <= deadline_at            -> TAKEN, delay_minutes = whole minutes
                                                 after window_end (late)
- nothing by deadline_at (+ grace, see rules_engine) -> MISSED

ASSUMPTION: "late" is measured from window_end, not window_start. When the
mobile app/emulator use a single time (window_end == window_start) this is
exactly "window_start + tolerance" as in the project brief. A taken dose with
delay_minutes == 0 is TAKEN_ON_TIME, > 0 is TAKEN_LATE (the ERD has no LATE
status, only TAKEN + delay_minutes).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models.enums import DoseStatus, JournalStatus


@dataclass(frozen=True)
class DoseInstants:
    scheduled_date: date
    scheduled_for: datetime
    window_end_at: datetime
    deadline_at: datetime


def dose_instants(
    scheduled_date: date, window_start: time, window_end: time, tolerance_minutes: int, tz: ZoneInfo
) -> DoseInstants:
    # datetime(..., tzinfo=ZoneInfo) resolves DST through zoneinfo's fold rules.
    start = datetime.combine(scheduled_date, window_start, tzinfo=tz)
    end = datetime.combine(scheduled_date, window_end, tzinfo=tz)
    return DoseInstants(
        scheduled_date=scheduled_date,
        scheduled_for=start,
        window_end_at=end,
        deadline_at=end + timedelta(minutes=tolerance_minutes),
    )


def is_scheduled_on(days_of_week: Iterable[int], day: date) -> bool:
    return day.isoweekday() in set(days_of_week)


def match_dose(
    occurred_at: datetime,
    window_start: time,
    window_end: time,
    tolerance_minutes: int,
    days_of_week: Iterable[int],
    tz: ZoneInfo,
    early_accept_minutes: int,
) -> DoseInstants | None:
    """Finds the dose (today or yesterday, local) whose acceptance window
    [scheduled_for - early, deadline_at] contains occurred_at. Yesterday is
    checked because deadline_at can cross midnight."""
    local_day = occurred_at.astimezone(tz).date()
    days = list(days_of_week)
    for day in (local_day, local_day - timedelta(days=1)):
        if not is_scheduled_on(days, day):
            continue
        inst = dose_instants(day, window_start, window_end, tolerance_minutes, tz)
        if inst.scheduled_for - timedelta(minutes=early_accept_minutes) <= occurred_at <= inst.deadline_at:
            return inst
    return None


def delay_minutes_for(taken_at: datetime, window_end_at: datetime) -> int:
    seconds_late = (taken_at - window_end_at).total_seconds()
    return max(0, int(seconds_late // 60))


def journal_status(status: str | None, delay_minutes: int | None) -> JournalStatus | None:
    if status == DoseStatus.PENDING:
        return JournalStatus.PENDING
    if status == DoseStatus.MISSED:
        return JournalStatus.MISSED
    if status == DoseStatus.TAKEN:
        return JournalStatus.TAKEN_LATE if (delay_minutes or 0) > 0 else JournalStatus.TAKEN_ON_TIME
    return None


@dataclass
class AdherenceSummary:
    scheduled: int = 0
    taken_on_time: int = 0
    taken_late: int = 0
    missed: int = 0
    pending: int = 0
    _delay_total: int = 0

    def add(self, status: str | None, delay_minutes: int | None) -> None:
        js = journal_status(status, delay_minutes)
        if js is None:
            return
        self.scheduled += 1
        if js is JournalStatus.TAKEN_ON_TIME:
            self.taken_on_time += 1
        elif js is JournalStatus.TAKEN_LATE:
            self.taken_late += 1
            self._delay_total += delay_minutes or 0
        elif js is JournalStatus.MISSED:
            self.missed += 1
        else:
            self.pending += 1

    @property
    def taken(self) -> int:
        return self.taken_on_time + self.taken_late

    @property
    def compliance_rate(self) -> float | None:
        """Percent of decided doses that were taken; None when nothing is decided yet."""
        decided = self.taken + self.missed
        return round(100.0 * self.taken / decided, 1) if decided else None

    @property
    def avg_delay_minutes(self) -> float | None:
        """Average delay over taken doses (on-time counts as 0)."""
        return round(self._delay_total / self.taken, 1) if self.taken else None
