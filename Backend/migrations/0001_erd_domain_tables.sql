-- PillCare domain tables, per the ERD column dictionary in
-- docs/HANDOVER_SYSTEM_ARCHITECTURE.md section 4 ("Pillbox ERD v2" on
-- dbdiagram.io, which could not be fetched directly).
--
-- users and push_tokens are owned by Prisma (Mobile/prisma) and are NOT
-- created here. Apply the Prisma migrations first.
--
-- Plain CREATE TABLE (no IF NOT EXISTS) on purpose: if a table already exists
-- in Supabase with different columns this migration fails loudly instead of
-- silently leaving a mismatched schema.
--
-- Enumerations are VARCHAR + CHECK (not Postgres ENUM types) so values can be
-- extended by a later migration without ALTER TYPE.
--
-- ASSUMPTION: columns whose type/nullability the ERD dictionary does not state
-- use the simplest choice consistent with the API List (nullable unless the
-- API requires a value).

-- ---------------------------------------------------------------- elderly
CREATE TABLE elderly (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name      VARCHAR(100) NOT NULL,
    nickname       VARCHAR(100),
    birth_date     DATE,
    gender         VARCHAR(10) CONSTRAINT elderly_gender_check CHECK (gender IN ('MALE', 'FEMALE')),
    contact_phone  VARCHAR(20),
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------ user_elderly_roles
CREATE TABLE user_elderly_roles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    elderly_id          UUID NOT NULL REFERENCES elderly (id) ON DELETE CASCADE,
    role                VARCHAR(10) NOT NULL
                        CONSTRAINT user_elderly_roles_role_check CHECK (role IN ('OWNER', 'ADMIN', 'PEMANTAU')),
    relationship_label  VARCHAR(50),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_elderly_roles_user_elderly_key UNIQUE (user_id, elderly_id)
);
CREATE INDEX user_elderly_roles_elderly_idx ON user_elderly_roles (elderly_id);
-- Exactly one OWNER per elderly (ownership transfer demotes first, then promotes).
CREATE UNIQUE INDEX user_elderly_roles_one_owner_idx ON user_elderly_roles (elderly_id) WHERE role = 'OWNER';

-- ------------------------------------------------ notification_preferences
CREATE TABLE notification_preferences (
    id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                       UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    elderly_id                    UUID NOT NULL REFERENCES elderly (id) ON DELETE CASCADE,
    push_enabled                  BOOLEAN NOT NULL DEFAULT TRUE,
    whatsapp_enabled              BOOLEAN NOT NULL DEFAULT FALSE,
    whatsapp_number               VARCHAR(20),
    -- API List: "notify_on_missed wajib true"
    notify_on_missed              BOOLEAN NOT NULL DEFAULT TRUE
                                  CONSTRAINT notification_preferences_missed_check CHECK (notify_on_missed),
    notify_on_taken               BOOLEAN NOT NULL DEFAULT FALSE,
    notify_on_device_offline      BOOLEAN NOT NULL DEFAULT TRUE,
    device_offline_after_minutes  INTEGER NOT NULL DEFAULT 10
                                  CONSTRAINT notification_preferences_offline_minutes_check
                                  CHECK (device_offline_after_minutes BETWEEN 1 AND 1440),
    notify_on_low_battery         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT notification_preferences_user_elderly_key UNIQUE (user_id, elderly_id)
);

-- ------------------------------------------------------------- invitations
CREATE TABLE invitations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    elderly_id          UUID NOT NULL REFERENCES elderly (id) ON DELETE CASCADE,
    invited_by_user_id  UUID REFERENCES users (id) ON DELETE SET NULL,
    invitee_email       VARCHAR(254) NOT NULL,
    invitee_user_id     UUID REFERENCES users (id) ON DELETE CASCADE,
    role                VARCHAR(10) NOT NULL
                        CONSTRAINT invitations_role_check CHECK (role IN ('ADMIN', 'PEMANTAU')),
    relationship_label  VARCHAR(50),
    status              VARCHAR(10) NOT NULL DEFAULT 'PENDING'
                        CONSTRAINT invitations_status_check CHECK (status IN ('PENDING', 'ACCEPTED', 'DECLINED', 'REVOKED')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    responded_at        TIMESTAMPTZ
);
CREATE INDEX invitations_elderly_idx ON invitations (elderly_id);

-- ----------------------------------------------------------------- devices
CREATE TABLE devices (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_code           VARCHAR(64) NOT NULL CONSTRAINT devices_device_code_key UNIQUE,
    elderly_id            UUID REFERENCES elderly (id) ON DELETE SET NULL,
    master_password_hash  VARCHAR(255),
    device_pin_hash       VARCHAR(255),
    device_nickname       VARCHAR(100),
    timezone              VARCHAR(64) NOT NULL DEFAULT 'Asia/Jakarta',
    auto_sync_timezone    BOOLEAN NOT NULL DEFAULT TRUE,
    chime_volume_level    VARCHAR(10) NOT NULL DEFAULT 'MEDIUM'
                          CONSTRAINT devices_chime_volume_check CHECK (chime_volume_level IN ('LOW', 'MEDIUM', 'HIGH')),
    status                VARCHAR(10) NOT NULL DEFAULT 'OFFLINE'
                          CONSTRAINT devices_status_check CHECK (status IN ('ONLINE', 'OFFLINE')),
    battery_percentage    INTEGER CONSTRAINT devices_battery_check CHECK (battery_percentage BETWEEN 0 AND 100),
    config_version        INTEGER NOT NULL DEFAULT 1,
    last_heartbeat        TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX devices_elderly_idx ON devices (elderly_id);

-- --------------------------------------------------------------- schedules
CREATE TABLE schedules (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id          UUID NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    slot_number        SMALLINT NOT NULL CONSTRAINT schedules_slot_check CHECK (slot_number BETWEEN 1 AND 8),
    row_type           VARCHAR(1) NOT NULL CONSTRAINT schedules_row_type_check CHECK (row_type IN ('A', 'B')),
    day_period         VARCHAR(10) NOT NULL
                       CONSTRAINT schedules_day_period_check CHECK (day_period IN ('MORNING', 'AFTERNOON', 'EVENING', 'NIGHT')),
    medication_name    VARCHAR(100),
    dosage_info        VARCHAR(255),
    window_start       TIME NOT NULL,
    window_end         TIME NOT NULL,
    tolerance_minutes  SMALLINT NOT NULL DEFAULT 30
                       CONSTRAINT schedules_tolerance_check CHECK (tolerance_minutes IN (15, 30, 45, 60)),
    -- ISO weekday numbers, 1 = Monday .. 7 = Sunday
    days_of_week       SMALLINT[] NOT NULL DEFAULT '{1,2,3,4,5,6,7}',
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- ASSUMPTION: a window does not cross midnight.
    CONSTRAINT schedules_window_order_check CHECK (window_end >= window_start),
    -- Row A = slots 1-4 (before meal), row B = slots 5-8 (after meal).
    CONSTRAINT schedules_row_matches_slot_check CHECK ((slot_number <= 4) = (row_type = 'A'))
);
CREATE INDEX schedules_device_idx ON schedules (device_id);

-- ----------------------------------------------------------- device_stocks
CREATE TABLE device_stocks (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id        UUID NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    slot_number      SMALLINT NOT NULL CONSTRAINT device_stocks_slot_check CHECK (slot_number BETWEEN 1 AND 8),
    remaining_units  INTEGER NOT NULL DEFAULT 0 CONSTRAINT device_stocks_remaining_check CHECK (remaining_units >= 0),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT device_stocks_device_slot_key UNIQUE (device_id, slot_number)
);

-- ----------------------------------------------------- refills / refill_items
CREATE TABLE refills (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id            UUID NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    refilled_by_user_id  UUID REFERENCES users (id) ON DELETE SET NULL,
    refilled_at          TIMESTAMPTZ NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX refills_device_idx ON refills (device_id, refilled_at DESC);

CREATE TABLE refill_items (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    refill_id        UUID NOT NULL REFERENCES refills (id) ON DELETE CASCADE,
    slot_number      SMALLINT NOT NULL CONSTRAINT refill_items_slot_check CHECK (slot_number BETWEEN 1 AND 8),
    unit_dose_count  INTEGER NOT NULL CONSTRAINT refill_items_count_check CHECK (unit_dose_count >= 0)
);
CREATE INDEX refill_items_refill_idx ON refill_items (refill_id);

-- ---------------------------------------------------------- telemetry_logs
CREATE TABLE telemetry_logs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id             UUID NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    schedule_id           UUID REFERENCES schedules (id) ON DELETE SET NULL,
    slot_number           SMALLINT CONSTRAINT telemetry_logs_slot_check CHECK (slot_number BETWEEN 1 AND 8),
    event_type            VARCHAR(40) NOT NULL,
    -- ASSUMPTION: NULL for non-dose rows (e.g. UNSCHEDULED_OPEN).
    status                VARCHAR(10) CONSTRAINT telemetry_logs_status_check CHECK (status IN ('TAKEN', 'MISSED', 'PENDING')),
    delay_minutes         INTEGER,
    actual_open_time      TIMESTAMPTZ,
    actual_close_time     TIMESTAMPTZ,
    chime_count           INTEGER,
    log_source            VARCHAR(40)
                          CONSTRAINT telemetry_logs_log_source_check
                          CHECK (log_source IN ('AUTO_SENSOR', 'MANUAL_CAREGIVER_CONFIRMATION')),
    confirmed_by_user_id  UUID REFERENCES users (id) ON DELETE SET NULL,
    confirmation_note     TEXT,
    recorded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX telemetry_logs_device_idx ON telemetry_logs (device_id, recorded_at DESC);

-- ----------------------------------------------------------- notifications
CREATE TABLE notifications (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    elderly_id           UUID REFERENCES elderly (id) ON DELETE CASCADE,
    device_id            UUID REFERENCES devices (id) ON DELETE SET NULL,
    telemetry_log_id     UUID REFERENCES telemetry_logs (id) ON DELETE SET NULL,
    type                 VARCHAR(30) NOT NULL
                         CONSTRAINT notifications_type_check
                         CHECK (type IN ('DOSE_LATE', 'DOSE_MISSED', 'DOSE_TAKEN', 'DEVICE_OFFLINE', 'DEVICE_ONLINE', 'LOW_BATTERY')),
    severity             VARCHAR(10) NOT NULL
                         CONSTRAINT notifications_severity_check CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
    message              TEXT NOT NULL,
    is_read              BOOLEAN NOT NULL DEFAULT FALSE,
    is_resolved          BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by_user_id  UUID REFERENCES users (id) ON DELETE SET NULL,
    resolved_at          TIMESTAMPTZ,
    resolution_note      TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX notifications_user_created_idx ON notifications (user_id, created_at DESC);

-- Same convention as the Prisma migrations: RLS on, no policies, so the
-- Supabase anon/authenticated roles cannot read these through PostgREST.
-- The backend connects as "postgres", which bypasses RLS.
ALTER TABLE elderly ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_elderly_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_stocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE refills ENABLE ROW LEVEL SECURITY;
ALTER TABLE refill_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
