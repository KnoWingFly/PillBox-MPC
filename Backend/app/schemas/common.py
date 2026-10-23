import re
from datetime import time
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator, PlainSerializer, StringConstraints

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


def _check_days(days: list[int]) -> list[int]:
    if not days:
        raise ValueError("at least one day is required")
    if any(d < 1 or d > 7 for d in days):
        raise ValueError("days are ISO weekdays 1 (Mon) .. 7 (Sun)")
    return sorted(set(days))


DaysOfWeek = Annotated[list[int], AfterValidator(_check_days)]
