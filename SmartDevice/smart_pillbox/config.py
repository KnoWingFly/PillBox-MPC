"""Central, hard-coded config for the simulator (MVP: no env-file layer yet)."""

import os
from pathlib import Path

# --- Physical layout ------------------------------------------------------
MEAL_TIMES = ["pagi", "siang", "sore", "malam"]          # 4 columns
MEAL_RELATIONS = ["sebelum_makan", "sesudah_makan"]      # 2 rows
NUM_CHAMBERS = len(MEAL_TIMES) * len(MEAL_RELATIONS)     # 8, per proposal

# --- Behaviour constraints (from Batasan Sistem) ---------------------------
SINGLE_ACTIVE_CHAMBER = True         # max 1 popped-up compartment at a time
DEFAULT_TOLERANCE_MINUTES = 30       # caregiver-configurable per schedule row
MAX_STOCK_CAPACITY = 30              # max sachets per compartment (monthly bulk refill)

# --- Simulated RTC ----------------------------------------------------------
DEFAULT_SIM_SPEED = 1.0              # 1.0 = realtime; e.g. 60.0 = 1 min/sec

# --- Chime -------------------------------------------------------------------
# Uncompressed PCM WAV (16-bit, 44.1/48 kHz); see core/audio.py. Missing file = system beep.
CHIME_SOUND_PATH = Path(
    os.environ.get("PILLCARE_CHIME_FILE") or Path(__file__).resolve().parent / "assets" / "chime.wav"
)
CHIME_VOLUME = 0.8                   # 0.0 - 1.0
CHIME_REPEAT_SECONDS = 5             # repeats while a chamber is popped up, until opened or missed

# --- Storage -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "pillbox_local.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "db" / "schema.sql"

# --- Backend sync --------------------------------------------------------------
# Override with PILLCARE_BACKEND_URL (e.g. http://192.168.1.10:8000) when the backend runs elsewhere.
BACKEND_ROOT_URL = os.environ.get("PILLCARE_BACKEND_URL", "http://localhost:8000").rstrip("/")
BACKEND_BASE_URL = BACKEND_ROOT_URL + "/api/v1"
# Periodic heartbeat + retry. Events do not wait for it: logging one schedules a sync after
# SYNC_DEBOUNCE_MS (so an open + close burst goes out as one batch).
SYNC_INTERVAL_SECONDS = 15
SYNC_DEBOUNCE_MS = 300
# Command channel (docs/DEVICE_CONTRACT.md §3); reconnects with capped exponential backoff.
WS_RECONNECT_MIN_MS = 1_000
WS_RECONNECT_MAX_MS = 30_000


def device_ws_url(device_code: str) -> str:
    return BACKEND_ROOT_URL.replace("http", "ws", 1) + f"/ws/device/{device_code}"
# Requests run in a worker thread, so generous timeouts never freeze the GUI. A remote
# database (e.g. Supabase in another region, ~400 ms per round-trip) makes one heartbeat
# take several seconds; a short timeout would drop responses the server already handled.
# Retrying before the server finished only re-sends the same events and adds load.
SYNC_HTTP_TIMEOUT_SECONDS = 40
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

