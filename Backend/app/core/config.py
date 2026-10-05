from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Backend/ (this file is Backend/app/core/config.py). Anchoring the .env path
# here makes it independent of the directory the server is launched from,
# which matters in a monorepo (Backend/, Mobile/, SmartDevice/).
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Priority: real environment variables > .env file > defaults.
    # Env var names are case-insensitive (pydantic-settings default).
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # `BATTERY_RATED_DAYS=` (empty) in .env means "unset", not "".
        env_ignore_empty=True,
    )

    app_name: str = "PillCare API"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # --- Database -------------------------------------------------------
    database_url: str  # Supabase session-pooler URI
    db_pool_size: int = 5
    db_max_overflow: int = 5
    # NullPool opens a fresh connection per session. Used by the test suite so
    # pooled asyncpg connections never cross event loops.
    db_use_null_pool: bool = False

    cors_origins: list[str] = ["http://localhost:8081"]

    # --- Caregiver auth -------------------------------------------------
    # "app_jwt": HS256 access tokens issued by the Mobile server
    #   (Mobile/src/server/tokens.ts, secret JWT_ACCESS_SECRET, sub = users.id).
    # "supabase": Supabase Auth access tokens verified against the project JWKS;
    #   sub is mapped to users through auth_identities.supabase_user_id.
    auth_mode: Literal["app_jwt", "supabase"] = "app_jwt"
    jwt_access_secret: SecretStr | None = None
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"

    # --- Device auth / provisioning -------------------------------------
    # Enables POST /api/v1/admin/devices (factory provisioning). Unset = disabled.
    provisioning_token: SecretStr | None = None
    device_secret_min_length: int = 16

    # --- Presence (online/offline) --------------------------------------
    device_heartbeat_interval_seconds: int = 15
    device_heartbeat_timeout_seconds: int = 45
    presence_check_interval_seconds: int = 5
    # Minimum time a device must stay offline before DEVICE_OFFLINE is written.
    # Each caregiver's notification_preferences.device_offline_after_minutes
    # can only make it longer.
    device_offline_notify_grace_seconds: int = 120
    ws_auth_timeout_seconds: float = 10.0
    command_ack_timeout_seconds: float = 10.0

    # --- Rules engine ---------------------------------------------------
    rules_engine_interval_seconds: int = 30
    rules_engine_lookback_days: int = 1
    # Extra wait after a dose deadline for in-flight telemetry.
    missed_decision_grace_seconds: int = 60
    # After a device reconnects, wait this long for its buffered flush.
    offline_flush_wait_seconds: int = 60
    # If the device stays offline this long past the deadline, decide MISSED
    # anyway so caregivers are not left uninformed (a later flush can still
    # upgrade the dose to TAKEN).
    offline_max_wait_minutes: int = 360
    # A "taken" event this many minutes before window_start still counts.
    dose_early_accept_minutes: int = 15

    # --- Telemetry ------------------------------------------------------
    telemetry_max_batch_size: int = 500
    # Emulator RTC can be fast-forwarded; events further in the future than
    # this are rejected.
    telemetry_max_future_skew_minutes: int = 10080

    # --- Thresholds -----------------------------------------------------
    low_battery_threshold_percent: int = 20
    low_stock_threshold_units: int = 3
    stock_capacity_per_slot: int = 30
    clock_drift_tolerance_seconds: int = 60
    # Rated runtime of a full battery, used for estimated_battery_days_remaining.
    # Unset = the estimate is returned as null.
    battery_rated_days: float | None = None
    pin_max_attempts: int = 5
    pin_lockout_seconds: int = 300

    enable_background_tasks: bool = True
    default_page_limit: int = 20
    max_page_limit: int = 100

    @field_validator("supabase_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg_driver(cls, v: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix):]
        return v

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"


# Cached so the .env file is read once, not per request. Use it as a
# dependency (Depends(get_settings)) so tests can override it via
# app.dependency_overrides.
@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
