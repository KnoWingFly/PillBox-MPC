-- 0005: "Buka bilik sekarang" for a missed dose (app/services/late_dose.py).
-- Until this device-clock instant the pillbox has the chamber popped up again,
-- and a lid-open for this MISSED dose is accepted as TAKEN (late) even though it
-- is after the dose's normal deadline. NULL = never released.
ALTER TABLE telemetry_logs ADD COLUMN IF NOT EXISTS late_release_until TIMESTAMPTZ;
