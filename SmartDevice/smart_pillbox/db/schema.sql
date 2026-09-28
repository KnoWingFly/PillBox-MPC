-- Local SQLite buffer for the smart-device simulator.
-- This mirrors what firmware would hold on-device (schedules + an
-- append-only event log used both as history and as the offline
-- telemetry queue: unsynced rows are simply events with synced = 0).

CREATE TABLE IF NOT EXISTS compartments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_relation     TEXT NOT NULL CHECK (meal_relation IN ('sebelum_makan', 'sesudah_makan')),
    meal_time         TEXT NOT NULL CHECK (meal_time IN ('pagi', 'siang', 'sore', 'malam')),
    schedule_time     TEXT NOT NULL,              -- "HH:MM", 24h local time
    tolerance_minutes INTEGER NOT NULL DEFAULT 30,
    refill_units      INTEGER NOT NULL DEFAULT 0, -- unit-dose packets currently loaded
    UNIQUE (meal_relation, meal_time)
);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    compartment_id INTEGER NOT NULL REFERENCES compartments (id),
    event_type     TEXT NOT NULL CHECK (
                       event_type IN ('POP_UP', 'DOOR_OPEN', 'DOOR_CLOSE', 'TAKEN', 'MISSED')
                   ),
    occurred_at    TEXT NOT NULL,   -- ISO-8601, from the simulated RTC
    synced         INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_unsynced ON events (synced);
CREATE INDEX IF NOT EXISTS idx_events_compartment ON events (compartment_id, occurred_at);
