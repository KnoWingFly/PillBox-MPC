import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

UTC_ZONE = ZoneInfo("UTC")


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def zone(name: str | None) -> ZoneInfo:
    """ZoneInfo for an IANA name; falls back to UTC (logged) if invalid."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("invalid_timezone", extra={"timezone": name})
    return UTC_ZONE


def as_aware(dt: datetime, tz: ZoneInfo) -> datetime:
    """Device clocks may send naive local timestamps (the emulator sends
    datetime.isoformat() without an offset). Naive values are interpreted in
    the device's configured timezone."""
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt
