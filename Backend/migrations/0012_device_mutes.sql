-- 0012: a caregiver stops following one pillbox without leaving the elderly profile
-- (Mobile/BACKEND_HANDOFF.md item 6). Roles stay on the elderly profile (user_elderly_roles); a row
-- here only hides that pillbox from the caregiver's list and stops new notifications and phone
-- pushes about it for them. DELETE /devices/{id}/membership adds a row, PUT removes it.
-- Rows go away with the device or the user, when the device is unpaired or moved to another
-- elderly, and when the caregiver leaves the profile (services/device_management.py, elderly.py).
CREATE TABLE device_mutes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    device_id   UUID NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT device_mutes_user_device_key UNIQUE (user_id, device_id)
);
-- Notification fan-out looks rows up by device; the unique key serves lookups by user.
CREATE INDEX device_mutes_device_idx ON device_mutes (device_id);
ALTER TABLE device_mutes ENABLE ROW LEVEL SECURITY;
