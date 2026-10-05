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

# --- Storage -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "pillbox_local.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "db" / "schema.sql"

# --- Backend sync --------------------------------------------------------------
# Override with PILLCARE_BACKEND_URL (e.g. http://192.168.1.10:8000) when the backend runs elsewhere.
BACKEND_BASE_URL = os.environ.get("PILLCARE_BACKEND_URL", "http://localhost:8000").rstrip("/") + "/api/v1"
SYNC_INTERVAL_SECONDS = 15
# Requests run in a worker thread, so generous timeouts never freeze the GUI. A remote
# database (e.g. Supabase in another region, ~400 ms per round-trip) makes one heartbeat
# take several seconds; a short timeout would drop responses the server already handled.
SYNC_HTTP_TIMEOUT_SECONDS = 12
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

