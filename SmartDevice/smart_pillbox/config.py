"""Central, hard-coded config for the simulator (MVP: no env-file layer yet)."""

import os
import re
from pathlib import Path

# --- Physical layout ------------------------------------------------------
MEAL_TIMES = ["pagi", "siang", "sore", "malam"]          # 4 columns
MEAL_RELATIONS = ["sebelum_makan", "sesudah_makan"]      # 2 rows
BEFORE_MEAL, AFTER_MEAL = MEAL_RELATIONS
NUM_CHAMBERS = len(MEAL_TIMES) * len(MEAL_RELATIONS)     # 8, per proposal
SLOT_NUMBERS = range(1, NUM_CHAMBERS + 1)                # 1-4 row A (before meal), 5-8 row B
# days_of_week uses ISO weekday numbers, 1 = Monday ... 7 = Sunday (contract §2.2).
DAYS_PER_WEEK = 7
ISO_WEEKDAYS = list(range(1, DAYS_PER_WEEK + 1))
SCHEDULE_TIME_FORMAT = "%H:%M"       # window_start / window_end on the wire and in SQLite

# --- Behaviour constraints (from Batasan Sistem) ---------------------------
SINGLE_ACTIVE_CHAMBER = True         # max 1 popped-up compartment at a time
DEFAULT_TOLERANCE_MINUTES = 30       # caregiver-configurable per schedule row
MAX_STOCK_CAPACITY = 30              # max sachets per compartment (monthly bulk refill)
MIN_STOCK = 0

# --- Simulated RTC ----------------------------------------------------------
REAL_TIME_SPEED = 1.0                # device seconds per real second of a real RTC
DEFAULT_SIM_SPEED = REAL_TIME_SPEED  # e.g. 60.0 = 1 min/sec
SIM_SPEEDS = (REAL_TIME_SPEED, 10.0, 60.0)   # the lab's speed choices
TICK_INTERVAL_MS = 1_000             # real time between scheduler ticks (the RTC handles speed)
# A tick that reads the RTC more than this far behind the previous one means the clock was set back.
CLOCK_BACKWARDS_GUARD_SECONDS = 1
# The lab's "+N" buttons (minutes): pop-up, then +5 / +30 to land late or missed.
CLOCK_JUMP_MINUTES = (5, 30, 60)
# "Jadwal Berikutnya" lands this long before the next pop-up.
NEXT_DOSE_LEAD_SECONDS = 5
# The RTC is corrected from the server clock (welcome message, heartbeat server_time) only when it
# is at least this far off, so network latency alone never moves it.
RTC_DRIFT_CORRECT_SECONDS = 30

# --- Chime -------------------------------------------------------------------
# Uncompressed PCM WAV (16-bit, 44.1/48 kHz); see core/audio.py. Missing file = system beep.
CHIME_SOUND_PATH = Path(
    os.environ.get("PILLCARE_CHIME_FILE") or Path(__file__).resolve().parent / "assets" / "chime.wav"
)
CHIME_VOLUME = 0.8                   # 0.0 - 1.0, until the config sets chime_volume_level
# Backend ChimeVolume (config chime_volume_level) -> QSoundEffect volume.
CHIME_VOLUME_LEVELS = {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 1.0}
CHIME_REPEAT_SECONDS = 5             # repeats while a chamber is popped up, until opened or missed
# chime_count estimate for COMPARTMENT_OPENED: one chime per this many seconds popped up.
CHIME_ESTIMATE_SECONDS = 2
# trigger_alarm without a usable duration_seconds rings this long.
DEFAULT_ALARM_DURATION_SECONDS = 10
MIN_ALARM_DURATION_SECONDS = 1

# --- Status bar ------------------------------------------------------------------
# How long a status bar message stays (ms).
STATUS_MESSAGE_SHORT_MS = 3_000
STATUS_MESSAGE_MS = 4_000
STATUS_MESSAGE_LONG_MS = 5_000
STATUS_MESSAGE_ALERT_MS = 8_000

# --- Storage -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "pillbox_local.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "db" / "schema.sql"
# SQLite tuning: WAL lets the GUI read while the sync worker writes; NORMAL is durable enough in WAL.
SQLITE_JOURNAL_MODE = "WAL"
SQLITE_SYNCHRONOUS = "NORMAL"
# Synced events older than this (device time) are deleted at start-up; unsynced ones never are.
SYNCED_EVENT_RETENTION_DAYS = 30
# A database that cannot be opened is moved aside with this suffix (+ timestamp) before recreating it.
CORRUPT_DB_SUFFIX = ".corrupt-"
CORRUPT_DB_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

# --- Logging -----------------------------------------------------------------
LOG_FILE_NAME = "pillbox.log"        # in the profile's folder, next to its database
LOG_FILE_MAX_BYTES = 1_000_000
LOG_FILE_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

# --- Virtual pillbox profiles ----------------------------------------------------
# Each simulator PROCESS is one pillbox ("main.py --profile pb2"), with its own database and so
# its own identity (device code + secret), schedules and event log. "default" keeps the original
# pillbox_local.db next to main.py; the others live in profiles/<name>/.
DEFAULT_PROFILE = "default"
VIRTUAL_PROFILES = (DEFAULT_PROFILE, "pb2", "pb3", "pb4")  # "Tambah Pillbox Virtual" allows up to 4
PROFILES_DIR = BASE_DIR / "profiles"
_PROFILE_NAME = re.compile(r"^[a-z0-9_-]{1,16}$")
PROFILE = DEFAULT_PROFILE  # set once at startup by use_profile()


def profile_dir(name: str) -> Path:
    return BASE_DIR if name == DEFAULT_PROFILE else PROFILES_DIR / name


def lock_path(name: str) -> Path:
    """Held by the process running that profile, so one profile never runs twice."""
    return profile_dir(name) / ".pillbox.lock"


def log_path(name: str) -> Path:
    return profile_dir(name) / LOG_FILE_NAME


# How often the status bar re-checks which other profiles run (a lock-file probe each).
PROFILE_CHECK_INTERVAL_SECONDS = 5
# "Tambah Pillbox Virtual" waits this long for the new process to take its lock.
PROFILE_LAUNCH_GUARD_SECONDS = 4


def use_profile(name: str) -> None:
    """Points this process at one profile. Call before creating the Database."""
    global PROFILE, DB_PATH
    if not _PROFILE_NAME.match(name):
        raise ValueError(f"Invalid profile name {name!r}: use 1-16 of a-z, 0-9, '-' or '_'")
    profile_dir(name).mkdir(parents=True, exist_ok=True)
    PROFILE = name
    DB_PATH = profile_dir(name) / "pillbox_local.db"

# --- device_state keys (db/schema.sql) ---------------------------------------------
STATE_DEVICE_CODE = "device_code"
STATE_DEVICE_SECRET = "device_secret"
STATE_PENDING_DEVICE_CODE = "pending_device_code"
STATE_PENDING_DEVICE_SECRET = "pending_device_secret"
STATE_IS_PAIRED = "is_paired"
STATE_CONFIG_VERSION = "config_version"
STATE_TIMEZONE = "timezone"
STATE_IS_REFILL_MODE = "is_refill_mode"
STATE_HEARTBEAT_INTERVAL_SECONDS = "heartbeat_interval_seconds"
STATE_CHIME_VOLUME_LEVEL = "chime_volume_level"
# Boolean values in device_state.
STATE_TRUE = "1"
STATE_FALSE = "0"
# "Nothing applied yet": the next config pull is a full one (also set when the identity changes).
INITIAL_CONFIG_VERSION = 0

# --- Backend sync --------------------------------------------------------------
# Override with PILLCARE_BACKEND_URL (e.g. http://192.168.1.10:8000) when the backend runs elsewhere.
BACKEND_ROOT_URL = os.environ.get("PILLCARE_BACKEND_URL", "http://localhost:8000").rstrip("/")
BACKEND_BASE_URL = BACKEND_ROOT_URL + "/api/v1"
# Periodic heartbeat + retry. Events do not wait for it: logging one schedules a sync after
# SYNC_DEBOUNCE_MS (so an open + close burst goes out as one batch).
SYNC_INTERVAL_SECONDS = 15  # until the backend sends heartbeat_interval_seconds
SYNC_DEBOUNCE_MS = 300
# Backend accepts at most 500 events per telemetry batch (contract §2.4).
FLUSH_CHUNK_SIZE = 200
# After a failed sync (server unreachable or 5xx) the next one waits
# min(MAX, MIN * 2^(failures-1)) seconds, randomized by +/- JITTER. MAX stays near the backend's
# 45 s offline timeout so a recovered server sees the device again quickly.
SYNC_BACKOFF_MIN_SECONDS = 5
SYNC_BACKOFF_MAX_SECONDS = 60
SYNC_BACKOFF_JITTER = 0.2
# closeEvent waits this long for a running sync or registration before closing the database.
SHUTDOWN_WAIT_MS = 3_000
# Command channel (docs/DEVICE_CONTRACT.md §3); reconnects with capped exponential backoff.
WS_RECONNECT_MIN_MS = 1_000
WS_RECONNECT_MAX_MS = 30_000
# Each reconnect delay is randomized by +/- this fraction, so many pillboxes reconnecting after a
# backend restart do not all hit it in the same second.
WS_RECONNECT_JITTER = 0.2
# Close codes from the backend (docs/DEVICE_CONTRACT.md §3).
WS_CLOSE_AUTH_FAILED = 4401  # key rejected or rotated: retrying soon cannot help
WS_CLOSE_REPLACED = 4000  # a newer connection with the same identity took over
WS_CLOSE_SERVER_ERROR = 1011  # server-side failure (e.g. database down): the key is fine, back off
# A WebSocket heartbeat the backend could not store is answered {"type": "error", "error": <this>}.
WS_HEARTBEAT_NOT_STORED = "heartbeat not stored, retry later"


def device_ws_url(device_code: str) -> str:
    return BACKEND_ROOT_URL.replace("http", "ws", 1) + f"/ws/device/{device_code}"
# Requests run in a worker thread, so generous timeouts never freeze the GUI. A remote
# database (e.g. Supabase in another region, ~400 ms per round-trip) makes one heartbeat
# take several seconds; a short timeout would drop responses the server already handled.
# Retrying before the server finished only re-sends the same events and adds load.
SYNC_HTTP_TIMEOUT_SECONDS = 40
# The heartbeat goes first in its own short request: the backend marks a device OFFLINE after 45 s
# without one, so a slow flush or config pull must never delay it.
HEARTBEAT_HTTP_TIMEOUT_SECONDS = 10
# Used until the backend's config (or welcome message) told the device its timezone.
DEFAULT_DEVICE_TIMEZONE = "Asia/Jakarta"
# Shown on the LCD; the label of the device timezone (e.g. WIB, WITA) comes from the zone itself.
FIRMWARE_VERSION = "v1"
# Simulated hardware readings sent in every heartbeat (no real radio or backup battery).
SIMULATED_WIFI_RSSI_DBM = -50
SIMULATED_RTC_BACKUP_ACTIVE = True
# Command ids remembered to answer a re-delivered command with its first ack instead of running it twice.
COMMAND_DEDUPE_SIZE = 64
REGISTER_HTTP_TIMEOUT_SECONDS = 30

# Files searched (in order) for PROVISIONING_TOKEN when the "Daftarkan Perangkat"
# button is pressed. The monorepo's Backend/.env is included so a local demo needs
# no copy-pasting; the env var PILLCARE_PROVISIONING_TOKEN wins over all of them.
ENV_FILES = [BASE_DIR / ".env", BASE_DIR.parent / "Backend" / ".env"]


def read_env_value(key: str) -> str | None:
    """Tiny .env reader (KEY=value lines, optional quotes); no extra dependency."""
    for path in ENV_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip().upper() == key.upper():
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
    return None


def provisioning_token() -> str | None:
    return os.environ.get("PILLCARE_PROVISIONING_TOKEN") or read_env_value("PROVISIONING_TOKEN")

