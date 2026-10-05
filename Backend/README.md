# PillCare Backend

FastAPI + async SQLAlchemy 2 + Supabase Postgres. Serves the caregiver app (REST) and the smart pillbox (REST and WebSocket), and runs two in-process background tasks: device presence and the missed-dose rules engine.

- Device protocol for the SmartDevice team: [`../docs/DEVICE_CONTRACT.md`](../docs/DEVICE_CONTRACT.md)
- OpenAPI docs while running: http://localhost:8000/docs

## Layout

```
app/
  main.py                 app, middleware, router wiring, lifespan (background tasks)
  core/                   config (env), security (JWT, device secret, PIN), errors, logging
  db/                     engine/session, SQL migration runner
  models/                 SQLAlchemy models (users/push_tokens mapped read-only: Prisma owns them)
  schemas/                Pydantic v2 request/response models
  api/deps.py             auth dependencies (caregiver JWT, device key), pagination
  api/routes/             thin routers: device_protocol, devices, schedules, elderly (+journal views),
                          journal, notifications, admin (provisioning), ws, health, me
  services/               all logic: telemetry, adherence, doses, rules_engine, presence,
                          connection_manager, notifications, device_management, schedules,
                          stock, elderly, journal, notification_feed, provisioning
migrations/               0001 = ERD tables, 0002 = backend additions not in the ERD
scripts/migrate.py        applies migrations/*.sql
scripts/fake_device.py    device test client (REST + WS, Wi-Fi off/on simulation)
tests/                    pytest suite against a real Postgres test database
```

## Setup

```bash
cp .env.example .env          # fill DATABASE_URL, JWT_ACCESS_SECRET, PROVISIONING_TOKEN
uv sync                       # installs runtime + dev dependencies
```

`JWT_ACCESS_SECRET` **must equal** `JWT_ACCESS_SECRET` in `Mobile/.env`. The Expo app sends access tokens minted by the Mobile server (HS256, `sub` = `users.id`). This backend verifies those tokens (`AUTH_MODE=app_jwt`). `AUTH_MODE=supabase` (JWKS) is still available, but the app does not use it today.

### Database

1. Apply the **Prisma migrations first**. They create `users`, `push_tokens`, etc., which the backend tables reference (from `Mobile/`: `npx prisma migrate deploy`).
2. Apply the backend migrations: `uv run python -m scripts.migrate`. They are recorded in `backend_schema_migrations`.

> ⚠️ Prisma only knows its own tables. **Do not run `prisma migrate dev` against the shared database**: it will see the backend tables as drift and offer to **reset the database**. Use `prisma migrate deploy`.

## Run

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Use **one worker**. Device WebSockets and pending command acks live in process memory, so a command handled by worker A cannot reach a socket held by worker B. The DB-side rules (missed doses, notifications) are idempotent and safe with several workers, but commands are not.

## Tests

The tests use a **real Postgres database**, never in-memory fakes. Set `TEST_DATABASE_URL` (env var or `Backend/.env`) to a **separate, disposable** database whose name contains `test`, e.g. a local Postgres 15+:

```bash
docker run -d --name pillcare-test-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=pillcare_test -p 5432:5432 postgres:16
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pillcare_test
uv run pytest
```

The suite **drops and recreates the `public` schema** of that database, applies `Mobile/prisma/migrations/*` and `Backend/migrations/*`, and truncates all tables between tests. It refuses to run if the name lacks `test` or equals `DATABASE_URL`.

Coverage: telemetry idempotency (duplicate `event_id`, also within a batch), on-time/late/missed classification, offline-flush ordering (out-of-order and naive timestamps), missed-dose rule idempotency across repeated passes and restarts, the offline rule (no "missed" until the flush wait), MISSED→TAKEN upgrade, role enforcement (Pemantau cannot trigger alarms or edit schedules), PIN rate limiting, `trigger_alarm` when the device is offline or REST-only, config versioning/304, and the command ack/timeout logic.

## Device test client

```bash
# 1. register a device (prints device_code, device_secret, qr_payload)
uv run python -m scripts.fake_device --provision --provisioning-token "$PROVISIONING_TOKEN"
# 2. pair it in the app (POST /api/v1/devices with qr_payload + PIN), then run it:
uv run python -m scripts.fake_device --device-code PB-XXXXXXXX --device-key '<secret>'
# 3. Wi-Fi off 20 s after start, back on 90 s later (buffer, offline detection, flush):
uv run python -m scripts.fake_device --device-code PB-XXXXXXXX --device-key '<secret>' --wifi-off-at 20 --wifi-off-for 90
```

Type `open 1`, `close 1`, `wifi off`, `wifi on`, `status`, `help` while it runs. `--transport rest` behaves like the PySide6 emulator (REST heartbeats only, no commands).

## API overview (prefix `/api/v1`)

| Area | Routes |
|---|---|
| Device protocol (X-Device-Key) | `POST /devices/{code}/heartbeat`, `GET /devices/{code}/config`, `POST /devices/{code}/config-ack`, `POST /devices/{code}/telemetry`, WS `/ws/device/{code}` |
| Devices | `POST /devices/pairing/scan`, `POST /devices`, `GET /devices`, `GET/PUT/DELETE /devices/{id}`, `POST /devices/{id}/join`, `PUT /devices/{id}/pin`, `GET /devices/{id}/status`, `GET /devices/{id}/clock`, `POST /devices/{id}/clock/calibrate`, `POST /devices/{id}/alarm`, `GET /devices/{id}/events` |
| Schedules | `GET/POST /devices/{id}/schedules`, `PUT/DELETE /devices/{id}/schedules/{schedule_id}`, `POST /devices/{id}/schedules/validate` |
| Stock | `POST /devices/{id}/refill-mode`, `POST/GET /devices/{id}/refills`, `GET /devices/{id}/stock` |
| Elderly | `POST/GET /elderly`, `GET/PUT/DELETE /elderly/{id}`, `POST/GET /elderly/{id}/caregivers`, `DELETE /elderly/{id}/caregivers/{caregiver_id}`, `POST /elderly/{id}/transfer-ownership`, `GET/PUT /elderly/{id}/notification-preferences` |
| Journal | `GET /elderly/{id}/journal/calendar?month=YYYY-MM`, `GET /elderly/{id}/journal/{YYYY-MM-DD}`, `GET /elderly/{id}/journal/summary?start&end`, `PUT /journal/dose-logs/{id}/manual-confirmation` |
| Notifications | `GET /notifications?tab=ALL\|LATE_MISSED\|RESOLVED&elderly_id&page&limit`, `GET /notifications/{id}`, `PUT /notifications/{id}/read`, `PUT /notifications/read-all`, `PUT /notifications/{id}/resolve` |
| Admin | `POST /admin/devices`, `POST /admin/devices/{code}/rotate-secret` (X-Provisioning-Token) |
| Misc | `GET /me`, `GET /health`, `GET /health/db` |

Auth, settings and push-token routes (`/auth/*`, `/setting*`) are served by the Mobile app's Expo API routes against the same database. They are not duplicated here.

Errors: `{"error": {"code", "message", "details"?}}`, the same format as the Mobile server.

## Push notifications

Notifications are written to the `notifications` table only. Real Expo/FCM delivery is a marked extension point: `app/services/notifications.py::dispatch_push`, which should read `push_tokens`.
