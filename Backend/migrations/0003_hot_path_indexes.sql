-- 0003: indexes for hot read paths found in the performance audit.
-- Additive only (no schema semantics change). Applied by scripts/migrate.py
-- in one transaction, so CONCURRENTLY is not used; the tables are small.

-- Journal day view (_first_notified: WHERE telemetry_log_id IN (...)) and the
-- ON DELETE SET NULL from telemetry_logs had no index on this FK column.
CREATE INDEX IF NOT EXISTS notifications_telemetry_log_idx
    ON notifications (telemetry_log_id)
    WHERE telemetry_log_id IS NOT NULL;

-- Unread badge, computed on every notification poll from the app
-- (GET /notifications, every NOTIFICATION_POLL_MS).
CREATE INDEX IF NOT EXISTS notifications_user_unread_idx
    ON notifications (user_id)
    WHERE is_read = false;

-- Open-alert counts per elderly (GET /elderly) and the LATE_MISSED tab.
CREATE INDEX IF NOT EXISTS notifications_user_elderly_open_idx
    ON notifications (user_id, elderly_id, created_at DESC)
    WHERE is_resolved = false;
