-- 0009: resolves architecture.md conflict 6. A caregiver without a notification_preferences
-- row has always been treated as notify_on_taken = TRUE by the code (services/notifications.py);
-- the column default said FALSE, so a row created later silently turned "dose taken" alerts off.
-- Decision: TRUE is intended. Existing rows keep the value they hold.
ALTER TABLE notification_preferences ALTER COLUMN notify_on_taken SET DEFAULT TRUE;
