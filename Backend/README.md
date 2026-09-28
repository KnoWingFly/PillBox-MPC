# PillCare Backend

FastAPI + SQLAlchemy 2.0 (async) + Supabase Postgres. Setup stage only:
config, DB session, health checks, and Supabase JWT verification.

## Run

```bash
cp .env.example .env      # then fill in values (file lives in Backend/)
uv sync
uv run fastapi dev app/main.py --port 8000
```

The `.env` path is anchored to `Backend/`, so it loads no matter which
directory you launch from. Real environment variables override `.env`.

- Docs:            http://localhost:8000/docs
- Liveness:        GET /health
- DB connectivity: GET /health/db
- Auth check:      GET /api/v1/me   (Authorization: Bearer <Supabase access token>)

## Where to find the values

| Variable | Where |
|---|---|
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` (project ref is in your dashboard URL) |
| `DATABASE_URL` | **Connect** button (top of dashboard) -> **Session pooler** -> copy URI |

The DB password in that URI is the one you set when creating the project.
No Supabase API key is needed by this backend yet.

## Config pattern

`app/core/config.py` defines `Settings` and a cached `get_settings()`.
Inject it with `Depends(get_settings)` (see `app/api/deps.py`) so tests can
swap it via `app.dependency_overrides[get_settings]`.
