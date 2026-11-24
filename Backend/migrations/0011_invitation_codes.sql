-- 0011: invitations by one-time code (services/invitations.py, docs/ROLES_FEATURE_PLAN.md R2).
-- An OWNER/ADMIN creates a PENDING invitation and shares its code; the invitee accepts it, so no
-- one is added to an elderly profile without consent and no email address is needed (or leaked).
-- Additive or loosening only: no row is changed or removed.

-- An invitation by code has no email address.
ALTER TABLE invitations ALTER COLUMN invitee_email DROP NOT NULL;

-- SHA-256 (hex) of the normalized code; the code itself is never stored.
ALTER TABLE invitations ADD COLUMN code_hash VARCHAR(64);
ALTER TABLE invitations ADD COLUMN expires_at TIMESTAMPTZ;
ALTER TABLE invitations ADD CONSTRAINT invitations_code_expiry_check
    CHECK (code_hash IS NULL OR expires_at IS NOT NULL);
-- Every invitation carries either an email (legacy invite) or a code.
ALTER TABLE invitations ADD CONSTRAINT invitations_email_or_code_check
    CHECK (invitee_email IS NOT NULL OR code_hash IS NOT NULL);

CREATE UNIQUE INDEX invitations_code_hash_key ON invitations (code_hash) WHERE code_hash IS NOT NULL;
-- GET /elderly/{id}/invitations lists the pending ones.
CREATE INDEX invitations_pending_idx ON invitations (elderly_id, created_at) WHERE status = 'PENDING';

ALTER TABLE attempt_counters DROP CONSTRAINT attempt_counters_scope_check;
ALTER TABLE attempt_counters ADD CONSTRAINT attempt_counters_scope_check
    CHECK (scope IN ('DEVICE_PIN', 'DEVICE_PIN_JOIN', 'PAIRING_SCAN', 'CAREGIVER_INVITE', 'INVITE_CODE'));
