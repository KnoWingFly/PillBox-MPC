# PillCare domain reference

Single source of domain facts for every AI tool and every teammate.
Derived from: project description PDF, API list, ERD (commit 341e9bd, 17 Oct 2026), and checked against the code on 23 Oct 2026. Wire-level device details: `docs/DEVICE_CONTRACT.md`.
If code disagrees with this file, stop and ask. If this file disagrees with the API list or ERD, the API list / ERD win and this file must be fixed.

## Product
PillCare = caregiver mobile app + cloud backend + emulated Smart Pillbox. The elderly person never touches a screen: they only open a physical compartment. All notifications and escalation go to caregivers (family).

## Roles (per elderly, table `user_elderly_roles`)
| Role | Notes |
|---|---|
| OWNER | Exactly one per elderly (partial unique index). Creator of the elderly profile. |
| ADMIN | Can manage schedules, stock, alarms, invites. |
| PEMANTAU | Read-only monitor. Joining a device with its PIN grants PEMANTAU. |

- OWNER only: delete elderly, transfer ownership, change device PIN, unpair device, revoke another caregiver (a caregiver may always leave on their own; the OWNER cannot be revoked).
- OWNER or ADMIN: edit elderly profile, invite caregivers, edit device settings, create/edit/delete schedules, refill mode and refills, trigger alarm, calibrate clock, manually confirm a dose.
- Any related caregiver: read everything for that elderly, resolve/read notifications.
- Unrelated caller gets `404 NOT_FOUND`; related but under-privileged gets `403 FORBIDDEN` (or `403 OWNER_ONLY`).

## Pillbox layout
- 8 slots. `slot_number` 1-8. Row A = slots 1-4 = before meal. Row B = slots 5-8 = after meal. DB check: `(slot <= 4) = (row = 'A')`.
- Columns = `day_period`: MORNING, AFTERNOON, EVENING, NIGHT (A1/B1 = MORNING ... A4/B4 = NIGHT). Derived server-side from the slot.
- LED: breathing yellow = before meal, breathing blue = after meal. Soft chime, max 60 dB.
- Hardware constraints (from the proposal): only one chamber active at a time; binary reed-switch door sensing only; unit-dose strips only; mechanical pinhole release; backup battery keeps RTC and mechanics for at least 12 hours; offline-first.
- One elderly can have several devices; one caregiver can manage several elderly. A device has 0 or 1 elderly (`elderly_id` NULL = not paired).

## Schedule rules (`schedules`)
- One live (not soft-deleted) schedule per (device, slot).
- `window_start` <= `window_end`, same day (windows never cross midnight).
- `tolerance_minutes` is one of 15, 30, 45, 60 (default 30).
- `days_of_week`: ISO numbers, 1 = Monday ... 7 = Sunday.
- Schedule conflicts on one device, per shared weekday (`Backend/app/services/schedules.py`): bare windows overlap -> `409 WINDOW_OVERLAP`; window + tolerance of one slot reaches into another's -> `409 SCHEDULE_TOO_CLOSE` (only one chamber can be popped up). Editing a slot whose door is open on the device -> `409 SLOT_IN_PROGRESS`.
- Every schedule or device-setting change bumps `devices.config_version` in the same transaction.

## Dose lifecycle
1. A dose is one row in `telemetry_logs` (unique per `schedule_id` + `scheduled_for`). `scheduled_for` = `window_start` on the local date; `deadline_at` = `window_end` + tolerance.
2. Status in DB: `PENDING` -> `TAKEN` | `MISSED`. The API exposes `TAKEN_ON_TIME` / `TAKEN_LATE`, derived from `delay_minutes` (0 = on time; measured from `window_end`, and stays 0 for `ON_TIME_GRACE_MINUTES`, default 10, after it).
3. Raw device reports land first in `device_events` (inbox, unique per `device_id` + `event_id`, stores the raw payload and `ACCEPTED|REJECTED`). Processed results go to `telemetry_logs`. Non-dose rows such as `UNSCHEDULED_OPEN` have `status` NULL.
4. Rules engine (background job in Backend): finds `PENDING` rows whose `deadline_at` has passed, sets `MISSED` with `log_source = SYSTEM_RULES_ENGINE`, creates notifications. It must be idempotent and safe with several workers.
5. Manual confirm (OWNER/ADMIN): override to `TAKEN_ON_TIME` / `TAKEN_LATE` with `log_source = MANUAL_CAREGIVER_CONFIRMATION`. Errors: `409 ALREADY_TAKEN_BY_DEVICE`, `409 DOSE_NOT_YET_DUE`.
6. `log_source`: `AUTO_SENSOR`, `MANUAL_CAREGIVER_CONFIRMATION`, `SYSTEM_RULES_ENGINE`.

## Notifications
- Types: DOSE_LATE, DOSE_MISSED, DOSE_TAKEN, DEVICE_OFFLINE, DEVICE_ONLINE, LOW_BATTERY, UNSCHEDULED_OPEN. Severity: INFO, WARNING, CRITICAL.
- One notification per incident per caregiver: unique (`event_key`, `user_id`), e.g. `DOSE_MISSED:<telemetry_log_id>`.
- Per caregiver and elderly, `notification_preferences` controls channels (push, WhatsApp) and event kinds. `notify_on_missed` must always be true (DB check + `422 MISSED_NOTIFICATION_CANNOT_BE_DISABLED`).
- `message` is localized to the recipient (`users.interface_language` ID/EN). Never build user-facing messages with inline literals; use a message catalog.
- Offline alert after `device_offline_after_minutes` (default 10, range 1-1440). Low-battery alerts are de-duplicated with `devices.low_battery_notified_at`.
- Tabs in the app: ALL, LATE_MISSED, RESOLVED. A resolved notification stores who/when/note.

## Device protocol
- Identity: `device_code` `PB-XXXXXXXX`; QR payload `pillcare://device/PB-XXXXXXXX`. Factory registers devices with `POST /admin/devices` (`X-Provisioning-Token`; feature is off when the token is unset); the device secret is returned once.
- Device auth: header `X-Device-Key` (secret). DB stores only its SHA-256 (`device_secret_hash`). Device PIN: 4 digits, stored as scrypt hash (`device_pin_hash`). `master_password_hash` is a leftover and unused.
- Pairing: scan QR (`POST /devices/pairing/scan`) -> `POST /devices` sets the PIN, creator becomes OWNER -> others `POST /devices/{id}/join` with the PIN (`429 TOO_MANY_ATTEMPTS` after repeated failures).
- Device -> server: `POST /devices/{code}/heartbeat`, `GET /devices/{code}/config?since_version=` (304 when current), `POST /devices/{code}/config-ack`, `POST /devices/{code}/telemetry` (batch, idempotent per `event_id`, `is_offline_flush`).
- Heartbeat carries battery, Wi-Fi RSSI, RTC time, `rtc_backup_active`, `config_version_applied`, and per-slot `door` + `stock_count`. The response carries `server_time`, `latest_config_version`, `config_update_available`, `heartbeat_interval_seconds`, `is_paired`.
- Telemetry event types (Backend `DeviceEventType` in `app/models/enums.py`, documented in `docs/DEVICE_CONTRACT.md`): POPUP_ACTIVATED, COMPARTMENT_OPENED, COMPARTMENT_CLOSED, ALARM_TIMEOUT, UNSCHEDULED_OPEN, REFILL_MAINTENANCE, ALARM_STARTED, ALARM_STOPPED, BATTERY_STATUS, NETWORK_RECOVERED. Never invent values; a new type needs an API list change first.
- Server -> device: WebSocket `/ws/device/{device_code}` (auth via `X-Device-Key` header or first message `{type:"auth", device_key}`). Commands: `trigger_alarm`, `time_sync`, `schedule_updated`, `refill_mode`, `release_slot`, each with `command_id`. The device must ack within `COMMAND_ACK_TIMEOUT_SECONDS` (default 10 s), otherwise the REST caller gets `504 DEVICE_ACK_TIMEOUT`. A new connection replaces the old one.
- Alarm from the app: `POST /devices/{id}/alarm` (slot or all slots, 5-600 s, default 60).

## Realtime to the app
`/ws/app` (Backend): first message `{type:"auth", token}` within 10 s, then the server pushes `notifications` (new rows in `items`) and `device` (the status body in `status`) messages after the DB commit. The Mobile app (`Mobile/lib/api.ts`) applies that data directly, refetches only when a message has none, and keeps polling as the fallback (notifications 5 s, status 10 s from `AppConfig`; 60 s while the socket is live).

## Time
All timestamps are `timestamptz`. A device has its own IANA timezone (`devices.timezone`, optional auto-sync); schedule times and `scheduled_date` are in the device's local time; caregivers have their own `users.timezone`. In the app, show dose times in the device's timezone.

## Localization
`users.interface_language` is ID or EN (default ID); `display_mode` LIGHT or DARK (default LIGHT, recommended for elderly visibility).
