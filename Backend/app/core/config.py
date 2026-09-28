from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Backend/ (this file is Backend/app/core/config.py). Anchoring the .env path
# here makes it independent of the directory the server is launched from,
# which matters in a monorepo (Backend/, Mobile/, SmartDevice/).
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Priority: real environment variables > .env file > defaults.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PillCare API"
    environment: str = "development"
    debug: bool = False

    supabase_url: str          # https://<project-ref>.supabase.co
    database_url: str          # Supabase session-pooler URI
    supabase_jwt_audience: str = "authenticated"

    cors_origins: list[str] = ["http://localhost:8081"]

    @field_validator("supabase_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

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
