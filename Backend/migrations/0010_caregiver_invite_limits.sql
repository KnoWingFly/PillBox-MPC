-- 0010: rate limit for caregiver invitations (services/elderly.py invite(), services/invitations.py).
-- Widens the scope CHECK of attempt_counters (0007) with CAREGIVER_INVITE, keyed by the inviting
-- user's id. Additive only: existing rows keep their scope; no data changes.
ALTER TABLE attempt_counters DROP CONSTRAINT attempt_counters_scope_check;
ALTER TABLE attempt_counters ADD CONSTRAINT attempt_counters_scope_check
    CHECK (scope IN ('DEVICE_PIN', 'DEVICE_PIN_JOIN', 'PAIRING_SCAN', 'CAREGIVER_INVITE'));
