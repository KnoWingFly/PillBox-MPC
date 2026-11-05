import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator, PlainSerializer, StringConstraints

from app.core.config import get_settings
from app.services.timeutil import is_valid_timezone

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _parse_hhmm(value: Any) -> Any:
    if isinstance(value, str):
        match = _HHMM.match(value)
        if not match:
            raise ValueError("must be HH:mm (24h)")
        return time(int(match.group(1)), int(match.group(2)))
    return value


HHMM = Annotated[
    time,
    BeforeValidator(_parse_hhmm),
    PlainSerializer(lambda t: t.strftime("%H:%M"), return_type=str),
]


def _check_tz(value: str) -> str:
    if not is_valid_timezone(value):
        raise ValueError("invalid IANA timezone")
    return value


TimeZoneName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64), AfterValidator(_check_tz)]
E164 = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+[1-9]\d{6,14}$")]
Name100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Label50 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
FreeText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]

# Largest UTC offset in use (UTC+14): "today" for the caller is at most this far ahead of UTC,
# so a birth date picked as today anywhere in the world is never rejected as future.
_MAX_UTC_OFFSET = timedelta(hours=14)


def _check_elderly_name(value: str) -> str:
    min_length = get_settings().elderly_name_min_length
    if len(value) < min_length:
        raise ValueError(f"must be at least {min_length} characters")
    return value


def _check_birth_date(value: date) -> date:
    latest_today = (datetime.now(UTC) + _MAX_UTC_OFFSET).date()
    if value > latest_today:
        raise ValueError("must not be in the future")
    max_age = get_settings().elderly_max_age_years
    try:
        earliest = latest_today.replace(year=latest_today.year - max_age)
    except ValueError:  # 29 Feb in a non-leap target year
        earliest = latest_today.replace(year=latest_today.year - max_age, day=latest_today.day - 1)
    if value < earliest:
        raise ValueError(f"must not be more than {max_age} years ago")
    return value


ElderlyName = Annotated[Name100, AfterValidator(_check_elderly_name)]
BirthDate = Annotated[date, AfterValidator(_check_birth_date)]


def _check_days(days: list[int]) -> list[int]:
    if not days:
        raise ValueError("at least one day is required")
    if any(d < 1 or d > 7 for d in days):
        raise ValueError("days are ISO weekdays 1 (Mon) .. 7 (Sun)")
    return sorted(set(days))


DaysOfWeek = Annotated[list[int], AfterValidator(_check_days)]
