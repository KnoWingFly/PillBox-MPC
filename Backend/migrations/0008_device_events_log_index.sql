-- 0008: index the device_events -> telemetry_logs foreign key, and drop a redundant index.
-- device_events.telemetry_log_id is ON DELETE SET NULL. Without an index, every dose row that
-- is deleted (drop_undecided_doses on unpair / schedule edit, forget_dose on a replayed pop-up)
-- scanned the whole device_events table, which only grows. Partial: most events have no log.
CREATE INDEX IF NOT EXISTS device_events_telemetry_log_idx
    ON device_events (telemetry_log_id) WHERE telemetry_log_id IS NOT NULL;

-- notifications_event_key_idx (event_key) duplicates the leading column of the unique
-- notifications_event_user_idx (event_key, user_id) WHERE event_key IS NOT NULL, which serves
-- every event_key lookup (an equality implies NOT NULL). Dropping it saves a write per insert.
DROP INDEX IF EXISTS notifications_event_key_idx;
