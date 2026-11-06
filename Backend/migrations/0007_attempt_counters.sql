-- 0007: brute-force counters that survive restarts (app/services/pin_attempts.py).
-- One row per (scope, subject): DEVICE_PIN (caregivers' PIN actions) and DEVICE_PIN_JOIN (join
-- by non-caregivers) are keyed by device id across ALL users, so making many accounts does not
-- multiply the guesses a 4-digit PIN allows, and strangers guessing cannot lock the caregivers
-- out; PAIRING_SCAN is keyed by user id. Fixed window: `attempts` counts attempts since `window_start`. Each attempt is
-- counted with one atomic upsert BEFORE the check runs, so parallel requests cannot all pass.
CREATE TABLE attempt_counters (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope         VARCHAR(20) NOT NULL CONSTRAINT attempt_counters_scope_check CHECK (scope IN ('DEVICE_PIN', 'DEVICE_PIN_JOIN', 'PAIRING_SCAN')),
    subject_key   VARCHAR(64) NOT NULL,
    attempts      INTEGER NOT NULL CONSTRAINT attempt_counters_attempts_check CHECK (attempts >= 0),
    window_start  TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT attempt_counters_scope_subject_key UNIQUE (scope, subject_key)
);
ALTER TABLE attempt_counters ENABLE ROW LEVEL SECURITY;
