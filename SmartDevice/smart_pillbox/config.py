"""Central, hard-coded config for the simulator (MVP: no env-file layer yet)."""

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

# --- Backend sync (stub — backend not built yet) -----------------------------
BACKEND_BASE_URL = "http://localhost:8000/api/v1"
SYNC_INTERVAL_SECONDS = 15
SYNC_HTTP_TIMEOUT_SECONDS = 2

