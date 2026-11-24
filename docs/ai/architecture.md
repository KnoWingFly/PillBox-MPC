# Architecture, data ownership and known conflicts

## Topology
```
Mobile app (Expo)  --HTTPS-->  Mobile auth server (Expo API routes + Prisma)   <Expo dev server>/api          API list section A
Mobile app (Expo)  --HTTPS/WS-> Backend (FastAPI)                               http://localhost:8000/api/v1   sections B-G, ws://.../ws/app (pushes carry the changed data; polling fallback)
SmartDevice emulator --HTTP/WS-> Backend (FastAPI)                             REST /api/v1/devices/{code}/*, ws://.../ws/device/{code}
Both servers --> the same Supabase Postgres (RLS enabled on every table, no policies)
```

## Data ownership (one writer per table)
| Owner | Tables | How they change |
|---|---|---|
| Mobile / Prisma | `users`, `auth_identities`, `refresh_tokens`, `password_reset_otps`, `push_tokens`, plus `auth_attempts` (auth-route rate limits, not an account table) (enums: `interface_language`, `display_mode`, `auth_provider`, `push_platform` as native Postgres ENUMs) | `Mobile/prisma/schema.prisma` + Prisma migration |
| Backend / SQL | `elderly`, `user_elderly_roles`, `notification_preferences`, `invitations`, `devices`, `device_stocks`, `refills`, `refill_items`, `schedules`, `device_events`, `telemetry_logs`, `notifications`, plus `attempt_counters` (PIN / pairing-lookup rate limits, 0007) (enums as VARCHAR + CHECK) | `Backend/migrations/NNNN_*.sql`, tracked in `backend_schema_migrations` |

Rules that follow from this:
- Backend treats the five account tables as read-only (it reads user profile, language and `push_tokens` to deliver notifications). It never runs DDL on them.
- Prisma never models the thirteen Backend tables (twelve ERD/domain tables plus `attempt_counters`).
- Backend tables may reference `users.id` with foreign keys; that is fine, the FK is authored in Backend SQL.

## Auth flow (as designed)
- Email/password: bcrypt in `users.password_hash`. Access token = JWT. Refresh token = opaque, stored as SHA-256, rotated within a `family_id`; reusing an old token revokes the whole family. Password reset OTP = HMAC-SHA256 with an attempt counter.
- Google SSO: Supabase Auth only does the Google sign-in. The Mobile auth server then maps the identity into `users` + `auth_identities` (`provider = GOOGLE`, `provider_user_id`, `supabase_user_id`) and issues the same app tokens. `google_linked` is derived in the API, not stored.
- The app talks to both servers with the app's own access JWT (claim `sub` = `users.id`). Supabase sessions are never used to call Backend.

## Known conflicts and recommended fixes
Items marked **Decided** describe what the code already does: follow it. The others are recommendations to confirm with the team; until confirmed, agents follow the "Safe default".

1. **Two migration tools on one database.**
   - Problem: Prisma Migrate and the Backend SQL runner both change the same Postgres. `prisma migrate dev` sees the Backend tables as drift and offers to reset the database (Backend/README.md).
   - Fix: author Prisma migrations against a local or throwaway Postgres, apply to the shared database only with `prisma migrate deploy`, then run `uv run python -m scripts.migrate` in `Backend/`. Never run `migrate dev`, `migrate reset` or `db push` on the shared database.
   - Safe default: `.claude/settings.json` denies `migrate reset` and `db push` and asks before any other `prisma migrate` command.

2. **JWT trust between the two servers. Decided.**
   - The Mobile auth server signs access tokens with HS256 using `JWT_ACCESS_SECRET` (`sub` = `users.id`). The Backend verifies them with the same `JWT_ACCESS_SECRET` (`AUTH_MODE=app_jwt`; `AUTH_MODE=supabase` exists but the app does not use it). Both `.env` files must hold the same value.
   - Never hard-code the secret; read it from env and fail fast when missing.

3. **Where the auth server runs. Decided: Vercel for the hosted web app, the Expo dev server (`:8081`) locally.**
   - `Mobile/vercel.json` builds the Expo web server output (`expo export --platform web`, `web.output: "server"` in `app.json`) and routes every request through `Mobile/api/index.js` (`expo-server/adapter/vercel`), so the Expo API routes under `src/app/api/` run as one Vercel function. `scripts/copy-prisma-engine.js` copies Prisma's `rhel-openssl-3.0.x` query engine (`binaryTargets` in `prisma/schema.prisma`) into that function. Setup and environment variables: `Mobile/README.md`, "Deploy the web app and auth API to Vercel".
   - Native builds call the hosted auth API through `EXPO_PUBLIC_API_URL`; the web app calls it on the same origin.
   - Keep auth logic in framework-agnostic modules under `Mobile/src/server/` so it can still move into FastAPI later without a rewrite.
   - Not decided: where the **Backend** (FastAPI) is hosted. It must stay one process (`Backend/CLAUDE.md`), so it cannot be a serverless function.

4. **Google verification path. Decided.**
   - The app signs in with Google through Supabase Auth; `src/app/api/auth/google+api.ts` verifies the Supabase user with the admin client (`SUPABASE_SECRET_KEY`), maps it into `users` + `auth_identities` (`supabase_user_id`), and issues the app's own tokens.

5. **Deleting an account while OWNER. Decided: reject with `409`.**
   - Problem: `DELETE /setting` removes the user; `user_elderly_roles` rows cascade, so an OWNER's elderly profile could end up with no OWNER (the partial unique index only prevents two).
   - Implemented in `Mobile/src/app/api/setting/index+api.ts`: while the user is OWNER of any elderly profile that is not soft-deleted, account deletion answers `409 CANNOT_REMOVE_OWNER`. This applies even when the user is the only caregiver: they must transfer ownership or delete the elderly profile first. (The earlier proposal to soft-delete the elderly automatically in that case was not implemented.)

6. **`notify_on_taken` default. Decided: TRUE.**
   - The code always treated a missing `notification_preferences` row as `notify_on_taken = true`. Migration `0009_notify_on_taken_default.sql` sets the column default to `TRUE` too, so behavior no longer depends on whether a row exists. Existing rows keep their value; `PUT /notification-preferences` still turns it off.

7. **Mockup vs API for the device secret.**
   - Problem: mockups say "Master Device Password (8+ characters)"; API and ERD use a 4-digit PIN (`device_pin`), and `master_password_hash` is unused. A 4-digit PIN has only 10,000 values.
   - Fix: follow API/ERD, relabel the screens as PIN, and enforce server-side attempt limiting (`429 TOO_MANY_ATTEMPTS`) on join, calibrate and PIN-change.

8. **RLS is on with no policies.**
   - Meaning: only a privileged server-side database role can read or write. The mobile app must never query Supabase tables with the publishable key, and `DATABASE_URL`, `SUPABASE_SECRET_KEY` and `JWT_ACCESS_SECRET` must never be `EXPO_PUBLIC_*`.

9. **Error body shape. Decided.**
   - Both servers answer `{"error": {"code": "DEVICE_ALREADY_PAIRED", "message": "...", "details": ...}}` (`details` optional), with the HTTP status from the API list. Sources: `Backend/app/core/errors.py`, `Mobile/src/server/http.ts`. The app maps `code` to a message in `Mobile/src/lib/api/error-message.ts` and refreshes its token only on `UNAUTHORIZED`.

## When you change a contract or schema
Update the API list and the ERD in the same PR, then update this folder (`docs/ai/`) if a rule changed.
