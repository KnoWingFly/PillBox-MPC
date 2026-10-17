# Performance findings: SmartDevice emulator

For the SmartDevice team. This comes from a read-only audit of `SmartDevice/`. Nothing in that folder was changed. Each item gives the file and line, whether the code proves it or it still needs a measurement, and a suggested patch. Contract references point to [`DEVICE_CONTRACT.md`](DEVICE_CONTRACT.md).

How the emulator reaches the backend today: a `QTimer` fires every `SYNC_INTERVAL_SECONDS` (15 s). Each tick runs one `SyncWorker` on a thread pool, which sends **a REST heartbeat first and then the telemetry flush**, one after the other. An event that happens between ticks waits in SQLite until the next tick.

## Summary: delay the emulator adds (device to backend)

| # | Cause | Worst-case added delay | Evidence |
|---|---|---|---|
| D1 | Events wait for the next sync tick | up to 15 s | Proven by code |
| D2 | Heartbeat runs before the flush, in the same worker | + one heartbeat (several seconds on a remote DB) | Proven by code |
| D3 | Wi-Fi "Online" does not trigger a sync | up to 15 s after reconnect | Proven by code |
| D4 | Tick skipped while a previous sync is still running | + 15 s per skipped tick | Proven by code |
| D5 | No WebSocket client | app → device: commands fail (409); config arrives only on the next heartbeat (≤ 15 s) | Proven by code |
| D6 | New TCP connection for every request (no `requests.Session`) | + 1 TCP (and TLS, if used) handshake per request | Hypothesis (needs measurement) |
| D7 | Timestamps are naive and come from the simulated clock | wrong `lag` numbers, not slower | Proven by code |

---

## D1. Events are sent only on the 15 s sync tick (Proven by code)

- `smart_pillbox/config.py:27` `SYNC_INTERVAL_SECONDS = 15`
- `smart_pillbox/gui/main_window.py:121-124` the only trigger for `flush_pending_events` is `_sync_timer`.
- `smart_pillbox/core/scheduler.py` writes events with `db.log_event(...)` (e.g. lines 98, 110, 148, 159, 192) but never asks for a sync.

A `COMPARTMENT_OPENED` that happens right after a tick waits about 15 s before the backend sees it. The caregiver app then adds its own polling delay (5 s by default).

**Suggested patch:** flush right away when an event is logged, with a short debounce so a burst (open + close) goes out as one batch:

```python
# main_window.py
from PySide6.QtCore import QTimer

# in __init__, after self._sync_timer is created:
self._flush_soon = QTimer(self)
self._flush_soon.setSingleShot(True)
self._flush_soon.setInterval(300)            # ms; batches open+close together
self._flush_soon.timeout.connect(self._on_sync_tick)
for hook in (self.scheduler.on_activated, self.scheduler.on_missed, self.scheduler.on_taken):
    hook.append(lambda *_: self._flush_soon.start())
```

The scheduler hooks fire for activation, missed and taken. If `UNSCHEDULED_OPEN` / `COMPARTMENT_CLOSED` have no hook, call `self._flush_soon.start()` where those are handled (`open_compartment` / `close_compartment` callers in the GUI).

## D2. The heartbeat blocks the flush (Proven by code)

- `smart_pillbox/gui/main_window.py:53-54`: `send_heartbeat(...)` and then `flush_pending_events(...)`.
- `smart_pillbox/core/sync.py:215` heartbeat `requests.post(...)` with `timeout=12` (`config.py:31`). When the heartbeat reports `config_update_available`, it also pulls the config and posts the ack before returning (`sync.py:233`, `245`, `265`).

The emulator's own comment (`config.py:28-30`) says each backend round-trip to Supabase was about 400 ms, so a heartbeat can take several seconds. Pending events wait for all of that.

**Suggested patch:** flush first, then heartbeat. The contract only asks for heartbeat-then-flush right after a reconnect (§5.3), and the backend accepts telemetry from an online device in any order, because every authenticated request marks the device seen.

```python
# main_window.py, SyncWorker.run
synced_count = sync.flush_pending_events(self.db)   # events first: they are what the caregiver waits for
sync.send_heartbeat(self.db, self.now_str, self.battery, self.is_online)
```

Keep the heartbeat first only for the reconnect case (see D3).

## D3. Turning Wi-Fi back on does not sync (Proven by code)

- `smart_pillbox/gui/main_window.py:464-472` `_toggle_wifi` flips `_is_online` and updates the button. It does not start a sync.
- `main_window.py:304-307` `_on_sync_tick` returns early while offline, so the buffered events wait for the next tick after reconnect: up to 15 s.

The backend's missed-dose rule waits `OFFLINE_FLUSH_WAIT_SECONDS` (60 s) after the device comes back. A slow flush therefore narrows the window in which a buffered "taken" event can arrive before the dose is marked missed. (A late flush still upgrades MISSED to TAKEN, but caregivers see a false alarm first.)

**Suggested patch:**

```python
def _toggle_wifi(self) -> None:
    self._is_online = not self._is_online
    ...  # existing button styling
    self._refresh_lcd()
    if self._is_online:
        self._on_sync_tick()   # contract §5.3: heartbeat, then flush immediately
```

Optionally queue a `NETWORK_RECOVERED` event first (contract §2.4: put it first in the flush batch).

## D4. Ticks are skipped while a sync is slow (Proven by code)

- `main_window.py:309-310`: `if self._is_syncing: return`.

If a sync takes longer than 15 s (heartbeat + config pull + ack + flush with 12 s timeouts each), the next tick is dropped and new events wait another full interval.

**Suggested patch:** remember that a sync was requested and run it again as soon as the current one finishes.

```python
def _on_sync_tick(self) -> None:
    ...
    if self._is_syncing:
        self._sync_again = True
        return
    ...

def _on_sync_finished(self, synced_count: int, message: str) -> None:
    self._is_syncing = False
    ...
    if getattr(self, "_sync_again", False):
        self._sync_again = False
        self._on_sync_tick()
```

## D5. No WebSocket, so app → device commands cannot arrive (Proven by code)

- `smart_pillbox/core/sync.py` uses REST only (`requests`). There is no client for `ws://<host>:8000/ws/device/{device_code}` (contract §3).
- Effect in the app: "Bunyikan alarm" and "Test" return `409 DEVICE_COMMAND_CHANNEL_UNAVAILABLE` while the emulator is online (`Backend/app/services/device_management.py`, `command_error_to_app_error`). Schedule changes reach the emulator only on its next heartbeat (≤ 15 s), plus the config pull and ack.

**Suggested patch (sketch):** a background thread with `websockets` (sync client) or `websocket-client`. This would be a new dependency in `SmartDevice/requirements.txt`, so check its current docs first.

```python
# smart_pillbox/core/ws_client.py
import json, threading, time
from websockets.sync.client import connect   # websockets >= 12

def run(url: str, key: str, on_command, stop: threading.Event) -> None:
    backoff = 1.0
    while not stop.is_set():
        try:
            with connect(url, additional_headers={"X-Device-Key": key}, open_timeout=10) as ws:
                backoff = 1.0
                for raw in ws:                           # welcome, heartbeat_ack, command, pong
                    msg = json.loads(raw)
                    if msg.get("type") == "command":
                        ok, result, error = on_command(msg["command"], msg.get("payload") or {})
                        ack = {"type": "ack", "command_id": msg["command_id"], "ok": ok}
                        ack.update({"result": result} if ok else {"error": error})
                        ws.send(json.dumps(ack))         # ack immediately: the app waits ≤ 10 s
        except Exception:
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)            # capped exponential backoff
```

`on_command` must hand the work to the Qt thread (for example with a `Signal`) and return quickly. For `schedule_updated`, start a sync instead of waiting for the next tick.

## D6. A new HTTP connection for every request (Hypothesis, needs measurement)

- `smart_pillbox/core/sync.py:75, 90, 164, 215, 245, 265` call `requests.get/post` directly. Each call opens a new TCP connection, with no keep-alive reuse.

This costs little on a LAN. Behind a tunnel or HTTPS (ngrok, a hosted backend) every request pays a TLS handshake. Measure it by comparing the emulator's request time with the backend's `http_request` `duration_ms` for the same request.

**Suggested patch:** one module-level `requests.Session()`. It is not thread-safe, so keep it per worker thread or guard it with a lock:

```python
import threading
_local = threading.local()

def _http() -> requests.Session:
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session

# then: _http().post(...), _http().get(...)
```

## D7. Naive, simulated timestamps (Proven by code; affects measurement, not speed)

- `smart_pillbox/db/database.py:151` stores `occurred_at.isoformat()` with no offset. `main_window.py` sends `self.clock.now().isoformat()` as `sent_at`/`rtc_time`, which comes from the simulated clock (`core/rtc.py:21-23`, `speed`).
- `sync.py:263` sends `applied_at` from the real clock (`datetime.now()`), so the two clocks are mixed.

The backend reads naive times in the device timezone (contract §6 row 3). With `speed != 1.0`, the backend's `lag_ms` for `backend_received` (event time vs server time) is meaningless. For latency tests, run at speed 1.0, or send `datetime.now().astimezone().isoformat()` for the wall-clock fields.

## Other observations (not latency)

- `sync.py:201` `wifi_rssi_dbm` is hardcoded to `-50`. The app's Wi-Fi label always shows "KUAT".
- `database.py:37` shares one `sqlite3` connection between the GUI thread and the sync worker (`check_same_thread=False`) without a lock. `sqlite3` serializes calls on one connection, but a GUI write can interleave between the worker's `get_unsynced_events()` and `mark_synced()`. That is harmless today, because only rows that were read get marked. Keep it that way if the flush logic changes.
- `sync.py:137-184` marks a whole batch synced on any 2xx. That matches the contract (§2.4: accepted, duplicate and rejected are all final).
- The telemetry payload never sets `is_offline_flush` (contract §2.4, §5.3). Sending `true` for the batches after a reconnect would let the backend logs separate offline flushes from live events.

## What to send back after measuring

With `PERF_TIMING_LOGS=true` on the backend, the `perf_timing` lines with `flow=iot_to_app`, `step=backend_received` carry `lag_ms` (event time to backend receipt) and the device `event_id`. Run the emulator at speed 1.0 and send:

1. `lag_ms` for 5 single taken events, before and after the D1+D2 patches.
2. The time from turning Wi-Fi on to the first `backend_received` line after it (D3). The emulator does not set `is_offline_flush` today, so match by `event_id`.
