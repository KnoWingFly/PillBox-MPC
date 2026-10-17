-- 0006: when a schedule's current timing took effect (app/services/schedules.py sets it on
-- create and whenever its time, tolerance, days or on/off state changes). The rules engine
-- only creates doses from then on: before, an edit kept created_at, so moving an old slot to
-- 23:15 at 22:32 created (and at once missed) YESTERDAY's 23:15 dose that never existed.
ALTER TABLE schedules ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ;
UPDATE schedules SET effective_from = COALESCE(updated_at, created_at) WHERE effective_from IS NULL;
ALTER TABLE schedules ALTER COLUMN effective_from SET DEFAULT now();
ALTER TABLE schedules ALTER COLUMN effective_from SET NOT NULL;
