---
paths:
  - "SmartDevice/**/*.py"
  - "Backend/app/**/*device*.py"
  - "Backend/app/**/*telemetry*.py"
  - "Backend/app/api/routes/ws.py"
  - "Backend/app/services/rules_engine.py"
  - "Backend/app/services/presence.py"
  - "Backend/app/services/connection_manager.py"
  - "Backend/app/services/doses.py"
  - "Backend/scripts/fake_device.py"
---

# Device protocol

Full context: docs/DEVICE_CONTRACT.md (the wire contract) and docs/ai/domain.md ("Device protocol", "Dose lifecycle").

- Device requests authenticate with the `X-Device-Key` header. The server stores only the SHA-256 and compares in constant time.
- Telemetry is idempotent per (`device_id`, `event_id`). The device generates `event_id` (uuid4) before sending and keeps the event until the server answers for it; `accepted`, `duplicate` and `rejected` are all final. A network error keeps it buffered.
- Offline-first: the device runs schedules, pop-up and alarms without network, buffers events in SQLite (the emulator's `events` table, `synced = 0`) and flushes in batches with `is_offline_flush = true`.
- Config flows by `config_version`: heartbeat reports the applied version, the device downloads with `since_version` (304 when current), applies atomically, then sends `config-ack`.
- WebSocket commands carry a `command_id` and must be acked within `COMMAND_ACK_TIMEOUT_SECONDS` (default 10 s). Timeouts, intervals and the heartbeat period are settings or server-provided values, never literals.
- Only one chamber may be active at a time. A dose is `PENDING -> TAKEN | MISSED`; `TAKEN_ON_TIME` / `TAKEN_LATE` are derived from `delay_minutes`.
- Do not invent event types. The current set is `DeviceEventType` in `Backend/app/models/enums.py`, documented in docs/DEVICE_CONTRACT.md; new ones need an API list change first.
- Timestamps are `timestamptz`; schedule times and `scheduled_date` use the device's timezone.
- Never log secrets, keys or PINs.
