# Backend handoff: QR pairing, multiple pillboxes, "Ingat saya"

The mobile app and the simulator were changed without touching `Backend/`, the Supabase schema,
RLS or the auth server (`Mobile/src/server`, `Mobile/src/app/api`). This list is what those parts
should add or change. Each item gives the contract the mobile app already expects, and where the
current workaround lives so it can be removed once the endpoint exists. Code workarounds carry
`TODO(backend-branch)` comments.

Error bodies keep the existing shape `{"error": {"code", "message", "details"?}}`.

## 1. Rate-limit pairing-code lookups (security)

`POST /api/v1/devices/pairing/scan` and `POST /api/v1/devices` have no attempt limit; only PIN
checks do (`services/pin_attempts.py`). A device code is 8 hex characters (2^32 values) and
`/pairing/scan` answers "known / unknown" for any code, so codes can be enumerated.

- Limit per user and per client IP, for example 10 lookups per minute.
- Over the limit: `429 TOO_MANY_ATTEMPTS` with a `Retry-After` header. The app already shows
  "Terlalu banyak percobaan. Coba lagi beberapa menit lagi." for this code.
- Note: the PIN limiter is in process memory, so it resets on restart and is per worker. A shared
  store (database or Redis) makes both limits real.

## 2. Stop leaking the elderly name from `/pairing/scan` (privacy)

`elderly_name_if_owned` is returned to any signed-in user who knows a code
(`services/device_management.py` `scan`). Contract stays the same, value changes:

```json
{ "device_id": "uuid", "is_registered": true, "elderly_name_if_owned": null }
```

Return the name only when the caller already has a role on that elderly profile. The app shows
the name when present and works without it.

## 3. Delete the caller's notifications for one pillbox

Today the app pages through `GET /notifications?elderly_id=` and calls
`DELETE /notifications/{id}` once per row (`Mobile/lib/devices.ts` `deleteMyNotificationsWhere`).
Used by "Hapus pillbox" and by "Hapus semua" in the Notifikasi tab, which must not clear other
pillboxes. Requested:

```
DELETE /api/v1/notifications?device_id={uuid}[&up_to_created_at={ISO8601}&up_to_id={uuid}]
200 {"deleted": 12}
```

- Deletes only rows with `user_id = caller` (never other caregivers' copies).
- `up_to_*` optional, same meaning as the existing bulk delete (keeps rows newer than the boundary).
- Unknown or foreign `device_id`: `200 {"deleted": 0}` (do not reveal whether it exists).

## 4. Filter the feed by pillbox

The feed is filtered on the phone (`Mobile/lib/notifications.ts`, `inActiveScope` in
`Mobile/lib/api.ts`), and the unread badge counts every pillbox because `unread_count` is per
user. Requested: `GET /api/v1/notifications?device_id={uuid}` (combinable with `tab`,
`elderly_id`), with `unread_count` computed with the same filter. Rows with `device_id = null`
(elderly-level) should be included when `elderly_id` matches the device's elderly.

## 5. Unpair semantics (`DELETE /api/v1/devices/{id}`)

Current behaviour (`device_management.py` `unpair`): soft-deletes the device's schedules, deletes
pending doses, clears `elderly_id`, PIN, `paired_at` and nickname. Notifications are untouched and
stay visible to every caregiver of the elderly profile. The app's dialog tells the OWNER that
removal affects every caregiver, and then purges the owner's own notifications (item 3).

Requested: `DELETE /api/v1/devices/{id}?purge_my_notifications=true` -> `204`, doing item 3 in
the same transaction. Please also confirm whether other caregivers' notifications for an unpaired
device should be kept (current) or removed.

## 6. Per-pillbox "leave" for non-owners (design question)

Roles live on the elderly profile (`user_elderly_roles`), so a PEMANTAU or ADMIN can only leave
the whole profile (`DELETE /elderly/{id}/caregivers/{me}`), which drops every pillbox of that
elderly. The app therefore offers non-owners "Sembunyikan" (hidden on this phone only).
If per-pillbox membership is wanted:

```
DELETE /api/v1/devices/{id}/membership -> 204
```

This needs a model change (a device-level membership or exclusion table). Until then hiding stays
local (`Mobile/lib/devices.ts` `saveHiddenPillboxIds`).

## 7. Factory reset for a device (simulator "Reset Identitas")

"Reset Identitas" in the simulator only forgets the code and secret locally; the old device row
stays on the server, still paired. Requested (provisioning token, like `/admin/devices`):

```
POST /api/v1/admin/devices/{device_code}/reset   (X-Provisioning-Token)
204
```

Unpairs the device and hard-deletes its schedules, doses, stock and notifications, so the
existing `ON DELETE CASCADE` / `SET NULL` rules (`migrations/0001`) are not needed for this.
The simulator would call it before forgetting its identity.

## 8. RLS

All backend tables have RLS enabled with no policies (`migrations/0001`, `0002`), so the
`anon` / `authenticated` roles cannot read them. The app only uses the API, so no change is
needed unless direct Supabase queries are planned.

## 9. Auth server (`Mobile/src/server`, `Mobile/src/app/api/auth`)

- **Absolute 30-day session cap.** Each refresh issues a new token with a fresh 30-day expiry
  (`src/server/tokens.ts` `rotateRefreshToken`), so a session never ends while it is used. The app
  enforces 30 days from login on the phone; the server should too: store the family's first login
  time and reject a refresh after 30 days with `401 REFRESH_TOKEN_INVALID`.
- **"Ingat saya" off.** The app keeps tokens in memory (native) or `sessionStorage` (web), but the
  refresh token stays valid on the server for 30 days. Accept `{"remember": false}` on
  `/api/auth/login` and `/api/auth/google` and issue a short-lived refresh token (for example 12 h).
- **Web token storage.** On web, "Ingat saya" keeps the refresh token in `localStorage`, readable by
  any script on the page (XSS risk). Safer: set the refresh token as an `HttpOnly; Secure;
  SameSite=Strict` cookie scoped to `/api/auth`, and have `/api/auth/refresh` read it from the
  cookie. The app's token store would then keep only the access token in memory on web.
- **Push tokens of ended sessions.** When a session ends without logout (app killed with
  "Ingat saya" off, or the 30-day cap), the push token stays registered to the user. Delete push
  tokens linked to a refresh-token family when that family is revoked or expires.

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
