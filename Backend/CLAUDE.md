# Backend — FastAPI (REST + WebSocket + rules engine)

Serves API list sections B-G and the WebSocket channels: REST under `/api/v1`, plus `/ws/app` and `/ws/device/{device_code}` (dev: `http://localhost:8000`, OpenAPI at `/docs`).
Section A (auth, `/setting`, push tokens) is NOT here: it lives in the Mobile auth server. Read `docs/ai/domain.md` and `docs/ai/architecture.md` before changing dose logic, auth or tables. Route overview: `Backend/README.md`. Device protocol: `docs/DEVICE_CONTRACT.md`.

## Stack and commands (from pyproject.toml and README.md)
- Python >= 3.11, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2 async + asyncpg, PyJWT. Package manager: uv.
- Install: `uv sync` (runtime + dev group).
- Run: `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`. Keep **one worker**: device sockets, `/ws/app` and pending command acks live in process memory.
- Migrate: `uv run python -m scripts.migrate` (applies `migrations/*.sql`, recorded in `backend_schema_migrations`). Prisma migrations must be applied first (from `Mobile/`: `pnpm exec prisma migrate deploy`).
- Test: `uv run pytest`. Needs `TEST_DATABASE_URL` pointing to a **separate, disposable** Postgres whose name contains `test`; the suite drops and recreates its `public` schema. Never point it at the shared database.
- Device test client: `uv run python -m scripts.fake_device --help`.
- There is no linter configured (ruff is not a dependency). Do not claim lint passed.
- Database: Supabase transaction pooler (port 6543) is recommended; it is auto-detected and asyncpg's prepared-statement cache is turned off for it (`DB_POOLER_MODE` overrides). See `.env.example` for every setting.

## Layout (match it; do not mass-move)
```
app/
  main.py            app, middleware, router wiring under /api/v1, lifespan (background tasks)
  core/              config.py (Settings, all env-driven values), security.py (JWT, device secret, PIN), errors.py, logging.py, timing.py
  db/                engine/session, migration runner
  models/            SQLAlchemy models; enums.py mirrors DB CHECK values. users/push_tokens are mapped read-only (Prisma owns them)
  schemas/           Pydantic request/response models from the API list
  api/deps.py        auth dependencies (get_current_user, get_authenticated_device) and pagination
  api/routes/        thin routers: device_protocol, devices, schedules, elderly, journal, notifications, admin, ws, health, me
  services/          all business logic and queries: telemetry, doses, adherence, rules_engine, presence, background,
                     leader (advisory lock), connection_manager + app_hub (WebSockets), notifications, schedules, stock, ...
migrations/          NNNN_name.sql; 0001-0006 exist, so the next is 0007
scripts/             migrate.py, fake_device.py, pair_device.py
tests/               pytest + pytest-asyncio (asyncio_mode=auto) + httpx against real Postgres
```
There is no separate repositories layer: queries live in `services/`. Do not add one unless the team agrees.

## Rules
- **Routers stay thin**: parse, authorize via `api/deps.py`, call a service, return a schema. No SQL in routers.
- **Ownership**: never write DDL or rows for the five account tables (`users`, `auth_identities`, `refresh_tokens`, `password_reset_otps`, `push_tokens`); read-only. See `.claude/rules/database-ownership.md`.
- **Auth**: caregiver = app JWT (HS256, `JWT_ACCESS_SECRET` shared with the Mobile server, `sub` = `users.id`, `AUTH_MODE=app_jwt`). Device = `X-Device-Key`, SHA-256 compared with `hmac.compare_digest`. Provisioning = `X-Provisioning-Token` on `/admin/devices` (disabled when unset). Role checks go through `services/access.py`.
- **Errors**: raise `AppError` / helpers from `app/core/errors.py`. Body shape is `{"error": {"code", "message", "details"?}}`, identical to the Mobile server. Keep `UNAUTHORIZED` for bad/expired caregiver tokens (the app refreshes only on that code). 404 for resources the caller cannot see, 403 for insufficient role.
- **Secrets**: device PIN with scrypt, device secret with SHA-256. Never log PINs, keys, tokens or OTPs. PIN endpoints are rate-limited (`services/pin_attempts.py`, `429 TOO_MANY_ATTEMPTS`).
- **Idempotent telemetry**: unique (`device_id`, `event_id`); answer per event `accepted | duplicate | rejected`; batch cap `TELEMETRY_MAX_BATCH_SIZE` (`413 BATCH_TOO_LARGE`).
- **Config changes**: any schedule or device-setting write bumps `devices.config_version` in the same transaction; `schedule_updated` and `/ws/app` pushes go out only after commit.
- **WebSocket commands**: carry a `command_id`; `COMMAND_ACK_TIMEOUT_SECONDS` and `WS_AUTH_TIMEOUT_SECONDS` come from settings.
- **Rules engine and presence**: in-process background tasks (`services/background.py`), one leader via Postgres advisory lock (`services/leader.py`), `FOR UPDATE SKIP LOCKED` on due `PENDING` rows, notifications deduped by the (`event_key`, `user_id`) unique index. Keep them idempotent.
- **Performance**: no N+1 (joins or `selectinload`), every list endpoint paginated (`page`, `limit`, `total`; `DEFAULT_PAGE_LIMIT` / `MAX_PAGE_LIMIT`), reuse indexes from `0003_hot_path_indexes.sql`, check heavy queries with `EXPLAIN` before adding an index (indexes need a migration).
- **No hard-coding**: values go in `core/config.py` Settings (+ `.env.example`), enums in `models/enums.py`. Notification text is localized by the recipient's `interface_language`.
- **Migrations**: SQL only, additive where possible, uuid PK `gen_random_uuid()`, `timestamptz`, `ENABLE ROW LEVEL SECURITY` on every new table (no policies). Update the ERD and API list in the same PR.
- **Tests**: add tests for dose lifecycle, idempotency and role checks next to the existing ones in `tests/`.
