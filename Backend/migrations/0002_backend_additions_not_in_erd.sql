-- Columns, values and one table that the ERD does NOT have but the backend
-- needs. Kept separate from 0001 so the ERD owners can review exactly what
-- was added and why. Every item here is listed under "Assumptions" in the
-- backend README / hand-off notes.

-- elderly: API "DELETE /elderly/{id}" is a soft delete; creator kept for audit.
ALTER TABLE elderly
    ADD COLUMN created_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    ADD COLUMN deleted_at TIMESTAMPTZ;

-- devices:
--  device_secret_hash      SHA-256 of the per-device secret sent as X-Device-Key
--                          (master_password_hash is left for its ERD meaning).
--  paired_at / pin_updated_at   returned by the API List.
--  config_version_applied / config_applied_at   config-ack reconciliation.
--  is_refill_mode          POST /devices/{id}/refill-mode.
--  wifi_rssi_dbm, rtc_*, chamber_doors   last heartbeat snapshot for
--                          GET /devices/{id}/status and /clock.
--  online_since / offline_since   presence transitions + grace periods.
--  low_battery_notified_at       de-duplicates LOW_BATTERY notifications.
ALTER TABLE devices
    ADD COLUMN device_secret_hash VARCHAR(64),
    ADD COLUMN paired_at TIMESTAMPTZ,
    ADD COLUMN pin_updated_at TIMESTAMPTZ,
    ADD COLUMN config_version_applied INTEGER,
    ADD COLUMN config_applied_at TIMESTAMPTZ,
    ADD COLUMN is_refill_mode BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN wifi_rssi_dbm INTEGER,
    ADD COLUMN rtc_time TIMESTAMPTZ,
    ADD COLUMN rtc_reported_at TIMESTAMPTZ,
    ADD COLUMN rtc_backup_active BOOLEAN,
    ADD COLUMN chamber_doors JSONB,
    ADD COLUMN online_since TIMESTAMPTZ,
    ADD COLUMN offline_since TIMESTAMPTZ,
    ADD COLUMN low_battery_notified_at TIMESTAMPTZ;
CREATE INDEX devices_status_heartbeat_idx ON devices (status, last_heartbeat);

-- schedules: soft delete keeps telemetry history linked; one live schedule per slot.
ALTER TABLE schedules ADD COLUMN deleted_at TIMESTAMPTZ;
CREATE UNIQUE INDEX schedules_one_live_per_slot_idx ON schedules (device_id, slot_number) WHERE deleted_at IS NULL;

-- refills: API "is_reset" (true = set stock to the given count instead of adding).
ALTER TABLE refills ADD COLUMN is_reset BOOLEAN NOT NULL DEFAULT FALSE;

-- telemetry_logs: dose identity and deadline.
--  elderly_id      history survives a device being moved/unpaired.
--  scheduled_date  local calendar date of the dose (device timezone).
--  scheduled_for   instant of window_start on that date.
--  deadline_at     window_end + tolerance; after it (plus grace) PENDING -> MISSED.
--  The unique index makes "one dose row per schedule per day" a DB guarantee,
--  so the rules engine and telemetry ingestion can never create a dose twice,
--  including across restarts and multiple workers.
ALTER TABLE telemetry_logs
    ADD COLUMN elderly_id UUID REFERENCES elderly (id) ON DELETE SET NULL,
    ADD COLUMN scheduled_date DATE,
    ADD COLUMN scheduled_for TIMESTAMPTZ,
    ADD COLUMN deadline_at TIMESTAMPTZ;
CREATE UNIQUE INDEX telemetry_logs_dose_key_idx ON telemetry_logs (schedule_id, scheduled_for)
    WHERE schedule_id IS NOT NULL AND scheduled_for IS NOT NULL;
CREATE INDEX telemetry_logs_pending_deadline_idx ON telemetry_logs (deadline_at) WHERE status = 'PENDING';
CREATE INDEX telemetry_logs_elderly_date_idx ON telemetry_logs (elderly_id, scheduled_date);

-- log_source: the rules engine needs a value that is neither sensor nor caregiver.
ALTER TABLE telemetry_logs DROP CONSTRAINT telemetry_logs_log_source_check;
ALTER TABLE telemetry_logs ADD CONSTRAINT telemetry_logs_log_source_check
    CHECK (log_source IN ('AUTO_SENSOR', 'MANUAL_CAREGIVER_CONFIRMATION', 'SYSTEM_RULES_ENGINE'));

-- notifications:
--  event_key   identifies the incident (e.g. "DOSE_MISSED:<log id>"); unique per
--              recipient so retries/restarts never duplicate, and resolving an
--              incident resolves it for every caregiver.
--  UNSCHEDULED_OPEN type: the device spec asks for a critical alert on forced
--              opening; the API List enum lacks it.
ALTER TABLE notifications ADD COLUMN event_key VARCHAR(200);
CREATE UNIQUE INDEX notifications_event_user_idx ON notifications (event_key, user_id) WHERE event_key IS NOT NULL;
CREATE INDEX notifications_event_key_idx ON notifications (event_key);
ALTER TABLE notifications DROP CONSTRAINT notifications_type_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_type_check
    CHECK (type IN ('DOSE_LATE', 'DOSE_MISSED', 'DOSE_TAKEN', 'DEVICE_OFFLINE', 'DEVICE_ONLINE', 'LOW_BATTERY', 'UNSCHEDULED_OPEN'));

-- device_events: raw inbox of every device event, keyed by the device-supplied
-- event_id. This is what makes telemetry idempotent: a re-sent event_id hits
-- the unique key and the original outcome is returned.
CREATE TABLE device_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id         UUID NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    event_id          VARCHAR(64) NOT NULL,
    batch_id          VARCHAR(64),
    event_type        VARCHAR(40) NOT NULL,
    slot_number       SMALLINT,
    schedule_ref      VARCHAR(64),
    occurred_at       TIMESTAMPTZ NOT NULL,
    chime_count       INTEGER,
    payload           JSONB NOT NULL,
    outcome           VARCHAR(10) NOT NULL CONSTRAINT device_events_outcome_check CHECK (outcome IN ('ACCEPTED', 'REJECTED')),
    reject_reason     TEXT,
    telemetry_log_id  UUID REFERENCES telemetry_logs (id) ON DELETE SET NULL,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT device_events_device_event_key UNIQUE (device_id, event_id)
);
CREATE INDEX device_events_device_occurred_idx ON device_events (device_id, occurred_at DESC);
ALTER TABLE device_events ENABLE ROW LEVEL SECURITY;
