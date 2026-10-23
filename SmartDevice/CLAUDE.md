# SmartDevice — Smart Pillbox emulator (simulates the ESP32 firmware and hardware)

Python 3.11+, PySide6 GUI, SQLite local buffer, `requests` for HTTP, `segno` for the pairing QR. There is no real hardware: this program IS the device. It talks to `Backend/` like the real firmware would. Read `docs/ai/domain.md` and `docs/DEVICE_CONTRACT.md` (the device <-> backend contract) before changing behavior. User-facing overview: `SmartDevice/README.md`.

## Commands (from README.md; this folder uses pip + venv, not uv)
- Setup once: `python -m venv .venv` then `.venv/bin/pip install -r requirements.txt`
- Run: `.venv/bin/python main.py` (default pillbox) or `.venv/bin/python main.py --profile pb2` (another independent pillbox; profiles: default, pb2, pb3, pb4)
- Test: `.venv/bin/pytest` (config in `pytest.ini`, `testpaths = tests`). As of 23 Oct 2026, 3 tests are stale against the code and fail (`test_database.py::test_log_event_and_sync_cycle` and `::test_update_schedule`, `test_scheduler.py::test_interact_ignored_when_not_active`); do not count them as caused by your change, and fix them only when asked. Tests are pure Python; for anything that needs Qt use `QT_QPA_PLATFORM=offscreen`.
- Backend location: `PILLCARE_BACKEND_URL` (default `http://localhost:8000`). Registration reads the provisioning token from `PILLCARE_PROVISIONING_TOKEN`, `SmartDevice/.env` or `../Backend/.env`.

## Layout (match it; do not mass-move)
```
main.py                     entry point: argument parsing, profile lock, QApplication
smart_pillbox/
  config.py                 all constants and env overrides (layout, tolerance, RTC, chime, URLs, timeouts, profiles)
  models.py                 data classes
  core/                     no Qt widgets: scheduler.py (dose windows, single active chamber, MISSED), rtc.py (simulated clock),
                            sync.py (REST heartbeat/config/telemetry), ws_client.py (command channel), audio.py (chime)
  db/                       database.py + schema.sql: device_state (key-value: identity, config_version, ...), compartments, events (log = outbox)
  gui/                      PySide6: main_window.py, compartment_widget.py (reused for all 8), lcd/qr/tray widgets, styles.py, icons.py
  utils/                    logging_config.py
  assets/                   chime.wav (16-bit PCM)
tests/                      test_scheduler.py, test_rtc.py, test_database.py
pillbox_local.db            database of the default profile (gitignored)
profiles/<name>/            database + lock of the other profiles pb2-pb4 (gitignored)
```
Background I/O (sync, registration) runs on `QThreadPool` workers (`QRunnable`) from `gui/main_window.py`. Keep that approach; do not introduce qasync.

## Behavior that must hold
- **Offline-first**: schedules live in SQLite and keep working without network. Every event is written to the local `events` table first (it doubles as the outbox: unsynced rows have `synced = 0`) and flushed later; a row is marked synced once the server answers for it (`accepted`, `duplicate` and `rejected` are all final, per `docs/DEVICE_CONTRACT.md`); on a network error the batch stays buffered.
- **Single active chamber**: at most one compartment popped up at a time; a second due compartment queues.
- **Dose flow**: window opens -> pop-up, breathing LED (yellow before meal, blue after meal), chime repeating every `CHIME_REPEAT_SECONDS` -> `POPUP_ACTIVATED`; lid open -> `COMPARTMENT_OPENED`; close -> `COMPARTMENT_CLOSED`; tolerance passes without opening -> `ALARM_TIMEOUT`; opening any chamber that is not the ACTIVE one (idle, taken or missed) -> `UNSCHEDULED_OPEN`; in refill mode every open logs `REFILL_MAINTENANCE` instead. Known gaps against the contract are listed in `docs/DEVICE_CONTRACT.md` §6; check it before "fixing" emulator behavior. The event types and required fields are in `docs/DEVICE_CONTRACT.md` and `Backend/app/models/enums.py` (`DeviceEventType`). Never invent new ones: the `events.event_type` CHECK in `db/schema.sql` allows only those values. `TAKEN` / `MISSED` exist only as the in-memory chamber state (`models.py`), never as event types.
- **Clock**: the simulated RTC (speed, +1 hour, jump to next dose) is sent in every heartbeat (`rtc_time`, `rtc_speed`); the backend follows it. Time-dependent logic must take the RTC, not `datetime.now()`, so tests can fast-forward.
- **Config sync**: heartbeat reports `config_version_applied`; on `config_update_available` or `schedule_updated`, fetch config, apply atomically, then `config-ack`.
- **Command channel** (`/ws/device/{device_code}`): handle the commands in `docs/DEVICE_CONTRACT.md` (`trigger_alarm`, `time_sync`, `schedule_updated`, `refill_mode`, `release_slot`) and always ack with the same `command_id` before the backend's ack timeout.
- **Credentials**: registration stores `device_code` and `device_secret` in the `device_state` key-value table of the profile's SQLite database (gitignored); `PILLCARE_DEVICE_CODE` / `PILLCARE_DEVICE_KEY` override them for the default profile only. Never commit, log or print them.

## Rules
- New values go in `config.py` (constants, or `os.environ.get` with a default when they must differ per machine). Colors and fonts go in `gui/styles.py`. Existing UI text is Indonesian and inline in the widgets; keep new text consistent with it.
- Reuse widgets (one compartment widget for all 8 slots). Network and disk work never runs on the GUI thread.
- Logic in `core/` and `db/` must stay testable without Qt. Add pytest tests for scheduler, sync/outbox and config changes.
- PINs and secrets are never logged.
