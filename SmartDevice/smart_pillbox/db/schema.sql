-- Local SQLite buffer for the smart-device simulator.
-- This mirrors what firmware would hold on-device (schedules + an
-- append-only event log used both as history and as the offline
-- telemetry queue: unsynced rows are simply events with synced = 0).

CREATE TABLE IF NOT EXISTS device_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Insert default state
INSERT OR IGNORE INTO device_state (key, value) VALUES ('config_version', '1');
INSERT OR IGNORE INTO device_state (key, value) VALUES ('is_refill_mode', '0');

CREATE TABLE IF NOT EXISTS compartments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_number INTEGER NOT NULL UNIQUE CHECK (slot_number BETWEEN 1 AND 8),
    meal_relation TEXT NOT NULL CHECK (meal_relation IN ('sebelum_makan', 'sesudah_makan')),
    meal_time TEXT NOT NULL CHECK (meal_time IN ('pagi', 'siang', 'sore', 'malam')),
    schedule_time TEXT NOT NULL, -- "HH:MM"
    tolerance_minutes INTEGER NOT NULL DEFAULT 30,
    medication_name TEXT NULL,
    stock_count INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    compartment_id INTEGER REFERENCES compartments (id),
    slot_number INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'POPUP_ACTIVATED', 
            'COMPARTMENT_OPENED', 
            'COMPARTMENT_CLOSED', 
            'ALARM_TIMEOUT', 
            'UNSCHEDULED_OPEN',
            'REFILL_MAINTENANCE'
        )
    ),
    occurred_at TEXT NOT NULL,
    chime_count INTEGER NOT NULL DEFAULT 0,
    synced INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_unsynced ON events (synced);
CREATE INDEX IF NOT EXISTS idx_events_compartment ON events (compartment_id, occurred_at);
