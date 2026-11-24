# Backend handoff: QR pairing, multiple pillboxes, "Ingat saya"

The mobile app and the simulator were changed without touching `Backend/`, the Supabase schema,
RLS or the auth server (`Mobile/src/server`, `Mobile/src/app/api`). This list is what those parts
should add or change. Each item gives the contract the mobile app already expects, and where the
current workaround lives so it can be removed once the endpoint exists. Code workarounds carry
`TODO(backend-branch)` comments.

Error bodies keep the existing shape `{"error": {"code", "message", "details"?}}`.

## 1. Rate-limit pairing-code lookups (security) — DONE (3 Nov 2026)

Implemented per user (not per IP: behind a proxy the client IP is not reliable):
`PAIRING_SCAN_MAX_ATTEMPTS` lookups per `PAIRING_SCAN_WINDOW_SECONDS` (default 30 per 5 min),
shared by `/pairing/scan` and `POST /devices`, answered `429 TOO_MANY_ATTEMPTS` + `Retry-After`.
Counters and the PIN limiter now live in Postgres (`attempt_counters`, migration 0007); a device
PIN is limited per device across all users. Original request:


`POST /api/v1/devices/pairing/scan` and `POST /api/v1/devices` have no attempt limit; only PIN
checks do (`services/pin_attempts.py`). A device code is 8 hex characters (2^32 values) and
`/pairing/scan` answers "known / unknown" for any code, so codes can be enumerated.

- Limit per user and per client IP, for example 10 lookups per minute.
- Over the limit: `429 TOO_MANY_ATTEMPTS` with a `Retry-After` header. The app already shows
  "Terlalu banyak percobaan. Coba lagi beberapa menit lagi." for this code.
- Note: the PIN limiter is in process memory, so it resets on restart and is per worker. A shared
  store (database or Redis) makes both limits real.

## 2. Stop leaking the elderly name from `/pairing/scan` (privacy) — DONE (3 Nov 2026)

The name is returned only to a caller with a role on that elderly profile. Original request:


`elderly_name_if_owned` is returned to any signed-in user who knows a code
(`services/device_management.py` `scan`). Contract stays the same, value changes:

```json
{ "device_id": "uuid", "is_registered": true, "elderly_name_if_owned": null }
```

Return the name only when the caller already has a role on that elderly profile. The app shows
the name when present and works without it.

## 3. Delete the caller's notifications for one pillbox — DONE (3 Nov 2026)

Implemented as specified below (`Backend/app/api/routes/notifications.py` `delete_all`) and used by
the app (`lib/api.ts` `deleteBackendNotificationsForDevice`, for "Hapus pillbox" and "Hapus semua").
The app used to page through `GET /notifications?elderly_id=` and call `DELETE /notifications/{id}`
once per row. Still to do: add the `device_id` parameter to the API list. Contract:

```
DELETE /api/v1/notifications?device_id={uuid}[&up_to_created_at={ISO8601}&up_to_id={uuid}]
200 {"deleted": 12}
```

- Deletes only rows with `user_id = caller` (never other caregivers' copies).
- `up_to_*` optional, same meaning as the existing bulk delete (keeps rows newer than the boundary).
- Unknown or foreign `device_id`: `200 {"deleted": 0}` (do not reveal whether it exists).

## 4. Filter the feed by pillbox — DONE (3 Nov 2026)

`GET /api/v1/notifications?device_id=` is implemented as requested (`notification_feed.list_feed`);
`unread_count` follows `device_id`/`elderly_id` (not `tab`). `GET /devices` and
`GET /elderly/{id}/caregivers` are paginated too (`page`, `limit`, `total`; the caregivers list
changed from a bare array to a page object). Still to do: add both to the API list. Original
request:


The feed is filtered on the phone (`Mobile/lib/notifications.ts`, `inActiveScope` in
`Mobile/lib/api.ts`), and the unread badge counts every pillbox because `unread_count` is per
user. Requested: `GET /api/v1/notifications?device_id={uuid}` (combinable with `tab`,
`elderly_id`), with `unread_count` computed with the same filter. Rows with `device_id = null`
(elderly-level) should be included when `elderly_id` matches the device's elderly.

## 5. Unpair semantics (`DELETE /api/v1/devices/{id}`) — DONE (24 Nov 2026)

`DELETE /api/v1/devices/{id}?purge_my_notifications=true` unpairs the pillbox and deletes the caller's
own notifications about it in the same transaction (`device_management.remove`). Decided: other
caregivers keep theirs (their history). The app sends one request (`lib/devices.ts` `unpairPillbox`).

## 6. Per-pillbox "leave" for non-owners — DONE (24 Nov 2026)

Decided: a per-pillbox mute, not per-device roles. `DELETE /api/v1/devices/{id}/membership` (204,
idempotent) records a row in `device_mutes` (migration 0012): the pillbox is hidden on every phone of
that caregiver (`GET /devices` items carry `is_muted`) and they get no new notifications or pushes
about it. Their role on the elderly profile, and so their access, is unchanged. `PUT` follows it
again. The OWNER gets `403` (they unpair instead). The app's "Sembunyikan" now mutes on the server;
pillboxes hidden on a phone before this are muted once on start-up (`context/devices-context.tsx`).

## 7. Factory reset for a device (simulator "Reset Identitas") — DONE (24 Nov 2026)

`POST /api/v1/admin/devices/{device_code}/reset` (X-Provisioning-Token) -> 204: unpairs the device
and hard-deletes its schedules, doses, raw events, stock, refills, mutes and every caregiver's
notifications about it (`provisioning.factory_reset`). The device row and its secret stay, so a real
device can be paired again. Caregivers' apps reload their list at once (`roles` push). The emulator
calls it before forgetting its identity (`SmartDevice/smart_pillbox/core/sync.py` `reset_on_server`).

## 8. RLS

All backend tables have RLS enabled with no policies (`migrations/0001`, `0002`), so the
`anon` / `authenticated` roles cannot read them. The app only uses the API, so no change is
needed unless direct Supabase queries are planned.

## 9. Auth server (`Mobile/src/server`, `Mobile/src/app/api/auth`) — DONE (24 Nov 2026)

- **Absolute session cap.** Rotation keeps the first token's `expires_at` (`tokens.ts`
  `claimAndIssue`), so a session ends `REFRESH_TOKEN_TTL_DAYS` (30) after sign-in however often it is
  refreshed; then `401 REFRESH_TOKEN_INVALID`.
- **"Ingat saya" off.** `/api/auth/login` and `/api/auth/google` accept `"remember": false` and issue
  a `REFRESH_TOKEN_SHORT_TTL_HOURS` (12) session. The app sends its checkbox value.
- **Web token storage.** With header `X-Token-Transport: cookie` (sent by the web app,
  `src/constants/auth.ts`) the refresh token is set as an `HttpOnly; SameSite=Strict` cookie scoped to
  `/api/auth` (`Secure` on https) and left out of the JSON; `/api/auth/refresh` and `/logout` read it
  from the cookie when the body has none, and logout clears it (`src/server/session-cookie.ts`). A
  short session uses a browser-session cookie. The web app keeps only the access token, in memory.
- **Push tokens of ended sessions.** `push_tokens.refresh_family_id` (Prisma migration
  `20261124000000_push_token_session`) records the session a phone registered under. Revoking a
  session (logout, reuse detection, password reset) deletes its push tokens; an expired one's are
  deleted on its last refresh attempt and on the next sign-in or push registration
  (`pruneEndedSessionPushTokens`).

## Contracts the app already relies on (no change needed)

| Call | Used for |
|---|---|
| `GET /devices` (`DeviceListItem`) | pillbox list: name, code, elderly, connectivity, battery, last seen |
| `GET /elderly?limit=100` (`my_role`) | role per pillbox; elderly picker when pairing |
| `POST /devices/pairing/scan` | code lookup before asking for the PIN |
| `POST /devices`, `POST /devices/{id}/join` | pair (new PIN) or join (existing PIN, PEMANTAU) |
| `GET /devices/{id}/status` | "pillbox sedang offline" warning after pairing |
| `PUT /devices/{id}` `{device_nickname}` | rename (OWNER/ADMIN) |
| `DELETE /devices/{id}` | remove (OWNER) |
| `GET /notifications?elderly_id=`, `DELETE /notifications/{id}` | per-pillbox feed and purge |
