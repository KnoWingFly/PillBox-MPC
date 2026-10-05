# PillCare Device ↔ Backend Contract

For the SmartDevice team. Describes exactly what the FastAPI backend (`Backend/`) expects from a pillbox: real firmware, the PySide6 emulator, or `Backend/scripts/fake_device.py`.

- REST base URL: `http://<host>:8000/api/v1`
- WebSocket URL: `ws://<host>:8000/ws/device/{device_code}`
- All timestamps are ISO 8601. Send them **with an offset** (`2026-09-30T07:15:22+07:00`). Naive timestamps (no offset) are accepted and read in the device's configured timezone (`devices.timezone`, default `Asia/Jakarta`).
- Errors always use this shape: `{"error": {"code": "DEVICE_KEY_INVALID", "message": "...", "details": ...}}`

---

## 1. Identity and authentication

Each device has:

| Item | What it is |
|---|---|
| `device_code` | Public ID printed in the QR code, e.g. `PB-1A2B3C4D`. The QR payload is `pillcare://device/PB-1A2B3C4D`. |
| device secret | Random string, about 43 characters, issued **once** at provisioning. The backend stores only its SHA-256 and compares in constant time. |

**Provisioning** (the "factory" step, before any caregiver pairs the device):

```http
POST /api/v1/admin/devices
X-Provisioning-Token: <PROVISIONING_TOKEN from Backend/.env>
Content-Type: application/json

{}                                   // or {"device_code": "sim-01", "device_secret": "<min 16 chars>"}
```
```json
{
  "id": "6f1c…",
  "device_code": "PB-1A2B3C4D",
  "device_secret": "q2V…(shown once)…",
  "qr_payload": "pillcare://device/PB-1A2B3C4D",
  "created_at": "2026-10-04T09:00:00Z"
}
```

Lost the secret? Issue a new one with `POST /api/v1/admin/devices/{device_code}/rotate-secret` (same header, body `{}`).

**Every device request** sends:

```
X-Device-Key: <device secret>
```

The `{device_id}` path segment in the device routes is the **device_code** (the device UUID also works). A wrong or unknown key returns `401 DEVICE_KEY_INVALID`. Unknown and known codes are rejected the same way. Never log the secret on the device.

---

## 2. REST endpoints (device → backend)

### 2.1 Heartbeat: `POST /devices/{device_code}/heartbeat`

Send one every **`heartbeat_interval_seconds`** (default **15 s**, returned in every response). After **45 s** without any signal (`DEVICE_HEARTBEAT_TIMEOUT_SECONDS`), the backend marks the device `OFFLINE`.

```json
{
  "sent_at": "2026-09-30T14:05:00+07:00",
  "battery_percent": 98,
  "wifi_rssi_dbm": -50,
  "rtc_time": "2026-09-30T14:05:00+07:00",
  "config_version_applied": 3,
  "rtc_backup_active": true,
  "chambers": [
    {"slot_number": 1, "door": "CLOSED", "stock_count": 7},
    {"slot_number": 2, "door": "OPEN",   "stock_count": 6}
  ]
}
```
- Required: `battery_percent`. Everything else is optional, but please send it.
- `stock_count` is the physical sachet count and is **authoritative**: it overwrites the backend's stock for that slot.
- `rtc_time` feeds the clock-drift view in the app.

Response `200`:
```json
{
  "server_time": "2026-09-30T07:05:00.123Z",
  "latest_config_version": 4,
  "config_update_available": true,
  "heartbeat_interval_seconds": 15,
  "is_paired": true
}
```
If `config_update_available` is true, pull the config (2.2).

### 2.2 Config pull: `GET /devices/{device_code}/config?since_version={applied}`

- `304 Not Modified` (no body) when `since_version >= latest`.
- `200`:
```json
{
  "config_version": 4,
  "timezone": "Asia/Jakarta",
  "chime_volume_level": "MEDIUM",
  "is_refill_mode": false,
  "schedules": [
    {
      "schedule_id": "0b8e…",
      "slot_number": 1,
      "window_start": "07:00",
      "window_end": "07:30",
      "tolerance_minutes": 30,
      "days_of_week": [1, 2, 3, 4, 5, 6, 7],
      "active": true,
      "medication_name": "Amlodipine",
      "dosage_info": "5 mg"
    }
  ]
}
```
- `days_of_week`: ISO weekday numbers, 1 = Monday … 7 = Sunday.
- Slots 1–4 = row A (before meal), 5–8 = row B (after meal). Columns are morning / afternoon / evening / night.
- A slot missing from `schedules` has no schedule. Treat it as inactive.

### 2.3 Config ack: `POST /devices/{device_code}/config-ack`

Send this right after the new config is saved locally.
```json
{"config_version": 4, "applied_at": "2026-09-30T14:05:05+07:00"}
```
Returns `200 {"acknowledged": true, "config_version_applied": 4}`, or `409 CONFIG_VERSION_UNKNOWN` if that version was never issued.

### 2.4 Telemetry: `POST /devices/{device_code}/telemetry`

```json
{
  "batch_id": "b1a7d6e4-4d1a-4c9f-8e3b-9a8c7b6d5e4f",
  "is_offline_flush": false,
  "events": [
    {
      "event_id": "4a0c6f0e-2f4e-4d7e-9d5b-0f7e1f0e9a11",
      "event_type": "COMPARTMENT_OPENED",
      "slot_number": 1,
      "schedule_id": "0b8e…",
      "occurred_at": "2026-09-30T07:15:22+07:00",
      "chime_count": 3
    }
  ]
}
```

| `event_type` | Meaning | Required extra fields |
|---|---|---|
| `POPUP_ACTIVATED` | Dose window started, chamber popped up, alarm started | `slot_number` |
| `COMPARTMENT_OPENED` | Lid opened during the dose window. **Counts as taken** (emulator semantics) | `slot_number`, optional `chime_count` |
| `COMPARTMENT_CLOSED` | Lid closed. Records close time. Counts as taken if no `OPENED` was seen for that dose | `slot_number` |
| `ALARM_TIMEOUT` | Device gave up: no pickup before its timeout. Marks the dose missed | `slot_number`, optional `chime_count` |
| `UNSCHEDULED_OPEN` | Lid forced open outside a dose. Creates a critical alert | `slot_number` |
| `REFILL_MAINTENANCE` | Lid used during refill mode (audit only) | — |
| `ALARM_STARTED` / `ALARM_STOPPED` | Alarm on/off, e.g. a remote `trigger_alarm` | optional `slot_number`, `command_id`, `reason` |
| `BATTERY_STATUS` | Battery or power change between heartbeats | `battery_percent`, optional `on_external_power` |
| `NETWORK_RECOVERED` | Wi-Fi came back. Put it first in the flush batch | — |

`schedule_id` is optional. The backend matches events to a dose by `slot_number` and time anyway.

**`event_id` rules**
- Must be unique per device, forever. Use a UUIDv4 generated **when the event happens**, not when it is sent. Max 64 characters.
- Re-sending the same `event_id` is always safe: it is a no-op and the response reports it as a `duplicate` with the **original** outcome. Never generate a new id for a retry.

Response `200`:
```json
{
  "server_time": "2026-09-30T07:15:23Z",
  "accepted": 1,
  "duplicates": 0,
  "rejected": [],
  "latest_config_version": 4,
  "results": [
    {"event_id": "4a0c…", "status": "accepted", "telemetry_log_id": "9d2e…", "reason": null}
  ]
}
```
- `results` follows the request order. `status` is `accepted`, `duplicate` or `rejected`.
- **All three are final.** Remove those events from the local buffer. Only a network error or a 5xx means "keep and retry".
- `rejected` covers an unknown `event_type`, a missing `slot_number`, or `occurred_at` too far in the future (default > 7 days, to allow fast-forwarded RTCs).
- Batch errors: `413 BATCH_TOO_LARGE` (more than 500 events: send in chunks), `422 VALIDATION_ERROR` (malformed JSON or fields), `401 DEVICE_KEY_INVALID`.
- If `latest_config_version` is above your applied version, pull the config now.

---

## 3. WebSocket (backend → device commands)

Connect to `ws://<host>:8000/ws/device/{device_code}` with header `X-Device-Key: <secret>`. A client that cannot set headers sends this first message within 10 s:
```json
{"type": "auth", "device_key": "<secret>"}
```
Auth failure closes the socket with code **4401**. A newer connection for the same device replaces the old one, which is closed with code **4000**.

**Server → device on connect:**
```json
{"type": "welcome", "server_time": "…", "heartbeat_interval_seconds": 15, "latest_config_version": 4}
```

**Device → server heartbeat** (same body as REST 2.1 plus `type`). Send it every `heartbeat_interval_seconds`:
```json
{"type": "heartbeat", "battery_percent": 97, "wifi_rssi_dbm": -55, "rtc_time": "…", "config_version_applied": 4, "chambers": [ … ]}
```
Reply:
```json
{"type": "heartbeat_ack", "server_time": "…", "latest_config_version": 4, "config_update_available": false, "heartbeat_interval_seconds": 15}
```
`{"type": "ping"}` gets `{"type": "pong", "server_time": "…"}`. Invalid messages get `{"type": "error", "error": "…"}`.

**Commands (server → device):**
```json
{
  "type": "command",
  "command_id": "e3b0c442-…",
  "command": "trigger_alarm",
  "payload": {"slot_number": 1, "duration_seconds": 60, "reason": "caregiver_request"},
  "issued_at": "2026-09-30T07:40:00Z"
}
```

| `command` | Payload | Device should | Ack `result` (suggested) |
|---|---|---|---|
| `trigger_alarm` | `slot_number` (nullable), `duration_seconds`, `reason` | Ring the chime and LED. Also log `ALARM_STARTED` with `command_id` | `{"ringing": true}` |
| `time_sync` | `server_time`, `timezone` | Set the RTC | `{"device_time_before": "…", "device_time_after": "…"}` |
| `schedule_updated` | `config_version` | Run `GET /config` then `POST /config-ack` | `{"config_version_applied": 5}` |
| `refill_mode` | `enabled` | Lock or unlock the lids | `{"is_refill_mode": true}` |

**Ack (device → server)**, sent once per command and as fast as possible:
```json
{"type": "ack", "command_id": "e3b0c442-…", "ok": true, "result": {"ringing": true}}
{"type": "ack", "command_id": "e3b0c442-…", "ok": false, "error": "speaker fault"}
```
The app's request waits up to `COMMAND_ACK_TIMEOUT_SECONDS` (default 10 s) for the ack:

| Situation | HTTP result for the caregiver |
|---|---|
| Ack `ok: true` | `200` with the ack |
| Ack `ok: false` | `502 DEVICE_REJECTED_COMMAND` |
| No ack in time | `504 DEVICE_ACK_TIMEOUT` |
| Socket dropped mid-command | `502 DEVICE_DISCONNECTED` |
| Device offline | `409 DEVICE_OFFLINE` |
| Online over REST but no WebSocket | `409 DEVICE_COMMAND_CHANNEL_UNAVAILABLE` |

`schedule_updated` and `refill_mode` are sent best-effort, without waiting for the ack. REST-only devices learn about the change from `config_update_available` in the next heartbeat.

---

## 4. Online / offline detection

- **Online:** set immediately by any authenticated signal: WS connect, a heartbeat (WS or REST), telemetry, or a config pull/ack.
- **Offline:** set by a WS close, or by no signal for `DEVICE_HEARTBEAT_TIMEOUT_SECONDS` (45 s). Uvicorn also pings WebSockets (every 20 s, 20 s timeout), so a silently dead socket is closed within about 40 s.
- **Notifications:** `DEVICE_OFFLINE` is written only after the device has stayed offline for at least `DEVICE_OFFLINE_NOTIFY_GRACE_SECONDS` (120 s), or each caregiver's `device_offline_after_minutes` if that is longer. `DEVICE_ONLINE` goes only to caregivers who got the matching `DEVICE_OFFLINE`. A short Wi-Fi blip flips the status but notifies nobody.

## 5. Offline buffering and flush (required behavior)

1. Write **every** event to local storage first, with its `event_id` and the **device's own `occurred_at`**. Do not wait for the network.
2. While offline, keep ringing alarms and evaluating schedules locally (offline-first). Do not drop events.
3. When Wi-Fi returns: **(a)** send a heartbeat (or open the WS), then **(b)** immediately flush the buffer oldest-first (`is_offline_flush: true`, ≤ 500 events per batch, `NETWORK_RECOVERED` first), then **(c)** pull the config if needed.
4. Remove an event from the buffer only after it appears in `results` (accepted, duplicate or rejected). On a timeout or 5xx, retry the same events with the same `event_id`s.
5. The backend processes each batch in `occurred_at` order, so arrival order does not matter.

**How the backend decides "missed" while you were offline.** A dose is due at `window_start`. It is on time until `window_end` and late until `window_end + tolerance_minutes` (the deadline). After the deadline the backend marks it `MISSED` **only if** one of these holds:
- the device is online and has been online for `OFFLINE_FLUSH_WAIT_SECONDS` (60 s), which gives your flush time to arrive, or
- the deadline passed more than `OFFLINE_MAX_WAIT_MINUTES` ago (6 h). The device is presumed gone, and caregivers must be told.

If a flushed `COMPARTMENT_OPENED`/`CLOSED` later proves the dose was taken before its deadline, the backend changes the dose to `TAKEN` and closes the missed-dose alerts. Flushing promptly keeps caregivers from seeing false alarms.

---

## 6. Where the current emulator differs from this contract

These are the differences observed in `SmartDevice/` (not modified by the backend work):

| # | Emulator today | Contract | Impact |
|---|---|---|---|
| 1 | ~~Hardcoded `sim-01` / `dummy-key`~~ **Fixed:** the "Koneksi Server" panel's "Daftarkan Perangkat" button provisions the emulator and stores its code + secret in `device_state` | Per-device secret from provisioning | None. `PILLCARE_DEVICE_CODE` / `PILLCARE_DEVICE_KEY` env vars can override the stored identity. |
| 2 | No WebSocket client | WS for commands and heartbeats | `trigger_alarm` and clock calibrate return `409 DEVICE_COMMAND_CHANNEL_UNAVAILABLE` while the emulator is online. Presence still works through REST heartbeats. |
| 3 | `occurred_at`, `rtc_time` and `applied_at` are naive (`datetime.isoformat()`) | Offset included | Works: naive times are read in the device timezone. Wrong if the emulator PC's timezone differs from the device's configured one. |
| 4 | Simulated RTC can run at 10×/60× and jump +1 h | Real time | Events "from the future" are accepted up to 7 days ahead. Server-side missed detection still uses real server time, so fast-forwarded demos can disagree with the server. |
| 5 | Lid **open** = taken (`scheduler.open_compartment`); `ALARM_TIMEOUT` fires at `schedule_time + tolerance` | Taken on open (or on close if no open); server deadline = `window_end + tolerance` | Same result when `window_end == window_start`. With a wider window the emulator times out earlier than the server would. |
| 6 | `update_schedules()` uses only `window_start` (ignores `window_end`) | Window `[start, end]` | See row 5. |
| 7 | Telemetry sends `schedule_id: null` | Optional | Works: matched by slot and time. |
| 8 | ~~Sends all unsynced events in one batch~~ **Fixed:** sends in chunks of 200 | ≤ 500 per batch | None. |
| 9 | Marks the whole batch synced on any 2xx | Per-event `results` | Fine: rejected events are final anyway. |
| 10 | Local `config_version` is reset to `0` when the device registers | — | Works: the first config after pairing is always pulled, and the GUI now applies pulled schedules live (no restart needed). |
| 11 | No `NETWORK_RECOVERED` or `BATTERY_STATUS` events; battery only in the heartbeat | Optional | None. |
| 12 | Heartbeat and flush skipped while "Wi-Fi: Offline"; heartbeat then flush on return | Same (§5) | Compatible. Offline is detected about 45 s after the toggle. |
