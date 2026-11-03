"""The device's own clock, extrapolated from its last report.

The emulator's lab clock can be moved (+1 hour, "Jadwal Berikutnya") and run
fast (10x, 60x) for demos. With FOLLOW_DEVICE_CLOCK on (the default), the
rules engine judges doses by that clock and the app shows the day by it, so
the pillbox, the backend and the app agree on which dose is due. A real
device keeps its RTC on real time (NTP / time_sync), so for it device time is
server time give or take a few seconds and nothing changes.

    device time = rtc_time + (now - rtc_reported_at) * rtc_speed

The device clock is trusted only within DEVICE_CLOCK_MAX_SKEW_MINUTES of server
time. Outside that (an RTC reset to 2000 after its backup battery died, a
wildly wrong clock) server time is used, so a broken clock can neither hold
back nor invent MISSED alerts.
"""

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, DateTime, Interval, and_, case, func, literal

from app.core.config import Settings
from app.models import Device


def extrapolated(device: Device, now: datetime) -> datetime | None:
    """The device clock at server time `now`; None until the device reported its RTC."""
    if device.rtc_time is None or device.rtc_reported_at is None:
        return None
    return device.rtc_time + (now - device.rtc_reported_at) * (device.rtc_speed or 1.0)


def device_now(device: Device, now: datetime, settings: Settings) -> datetime:
    """The "now" doses of this device are judged by."""
    if not settings.follow_device_clock:
        return now
    clock = extrapolated(device, now)
    if clock is None or abs(clock - now) > timedelta(minutes=settings.device_clock_max_skew_minutes):
        return now
    return clock


def device_now_sql(now: datetime, settings: Settings) -> ColumnElement[datetime]:
    """device_now() as a SQL expression over the joined devices row, for WHERE clauses."""
    server_now = literal(now, DateTime(timezone=True))
    if not settings.follow_device_clock:
        return server_now
    device_seconds = func.extract("epoch", server_now - Device.rtc_reported_at) * func.coalesce(Device.rtc_speed, 1.0)
    clock = Device.rtc_time + func.make_interval(0, 0, 0, 0, 0, 0, device_seconds, type_=Interval)
    skew = timedelta(minutes=settings.device_clock_max_skew_minutes)
    return case(
        (
            and_(
                Device.rtc_time.is_not(None),
                Device.rtc_reported_at.is_not(None),
                clock.between(literal(now - skew, DateTime(timezone=True)), literal(now + skew, DateTime(timezone=True))),
            ),
            clock,
        ),
        else_=server_now,
    )
