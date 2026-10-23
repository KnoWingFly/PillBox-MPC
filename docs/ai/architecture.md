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
| Mobile / Prisma | `users`, `auth_identities`, `refresh_tokens`, `password_reset_otps`, `push_tokens` (enums: `interface_language`, `display_mode`, `auth_provider`, `push_platform` as native Postgres ENUMs) | `Mobile/prisma/schema.prisma` + Prisma migration |
| Backend / SQL | `elderly`, `user_elderly_roles`, `notification_preferences`, `invitations`, `devices`, `device_stocks`, `refills`, `refill_items`, `schedules`, `device_events`, `telemetry_logs`, `notifications` (enums as VARCHAR + CHECK) | `Backend/migrations/NNNN_*.sql`, tracked in `backend_schema_migrations` |

Rules that follow from this:
- Backend treats the five account tables as read-only (it reads user profile, language and `push_tokens` to deliver notifications). It never runs DDL on them.
- Prisma never models the twelve Backend tables.
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

3. **The auth server runs on the Expo dev server (`:8081`).**
   - Problem: that host exists only during `expo start`. A real deployment needs a place to host Expo API routes (check the current Expo docs, I did not verify hosting options), or auth moves into FastAPI later.
   - Fix: for the course demo keep it; keep auth logic in framework-agnostic modules under `Mobile/src/server/` so it can move without a rewrite.

4. **Google verification path. Decided.**
   - The app signs in with Google through Supabase Auth; `src/app/api/auth/google+api.ts` verifies the Supabase user with the admin client (`SUPABASE_SECRET_KEY`), maps it into `users` + `auth_identities` (`supabase_user_id`), and issues the app's own tokens.

5. **Deleting an account can orphan an elderly profile.**
   - Problem: `DELETE /setting` removes the user; `user_elderly_roles` rows cascade, so an OWNER's elderly profile can end up with no OWNER (the partial unique index only prevents two).
   - Fix: reject account deletion with `409` while the user is OWNER of an elderly that still has other caregivers (they must transfer ownership first); if the user is the only caregiver, soft-delete the elderly (`deleted_at`) in the same transaction.

6. **`notify_on_taken` default differs from code.**
   - Problem: the column defaults to false, but code treats a missing row as true, so behavior depends on whether a row exists.
   - Fix: create the `notification_preferences` row whenever a caregiver gains access to an elderly (create, invite, join), then remove the "missing row = true" branch.

7. **Mockup vs API for the device secret.**
   - Problem: mockups say "Master Device Password (8+ characters)"; API and ERD use a 4-digit PIN (`device_pin`), and `master_password_hash` is unused. A 4-digit PIN has only 10,000 values.
   - Fix: follow API/ERD, relabel the screens as PIN, and enforce server-side attempt limiting (`429 TOO_MANY_ATTEMPTS`) on join, calibrate and PIN-change.

8. **RLS is on with no policies.**
   - Meaning: only a privileged server-side database role can read or write. The mobile app must never query Supabase tables with the publishable key, and `DATABASE_URL`, `SUPABASE_SECRET_KEY` and `JWT_ACCESS_SECRET` must never be `EXPO_PUBLIC_*`.

9. **Error body shape. Decided.**
   - Both servers answer `{"error": {"code": "DEVICE_ALREADY_PAIRED", "message": "...", "details": ...}}` (`details` optional), with the HTTP status from the API list. Sources: `Backend/app/core/errors.py`, `Mobile/src/server/http.ts`. The app maps `code` to a message in `Mobile/src/lib/api/error-message.ts` and refreshes its token only on `UNAUTHORIZED`.

## When you change a contract or schema
Update the API list and the ERD in the same PR, then update this folder (`docs/ai/`) if a rule changed.
