-- 0004: how fast the device's RTC runs relative to real time (1.0 = real time).
-- The emulator's lab clock can run at 10x / 60x for demos; with rtc_time and
-- rtc_reported_at this lets the backend and the app extrapolate the device
-- clock between heartbeats (app/services/device_clock.py). NULL = 1.0.
ALTER TABLE devices ADD COLUMN IF NOT EXISTS rtc_speed DOUBLE PRECISION;
