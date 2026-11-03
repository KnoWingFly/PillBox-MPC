# Backend + IoT reliability audit — 2026-11-03

Scope: `Backend/` (REST, WebSocket, rules engine, DB access, migrations), the `SmartDevice/` emulator's connection to it, and the wire contract (`docs/DEVICE_CONTRACT.md`). Audit mode: no existing file was changed. New files are this report and throwaway scripts in `docs/audits/scratch/`.

## 1. Executive summary

| Area | Verdict | Critical | High | Medium | Low |
|---|---|---|---|---|---|
| Contract conformance | **Mostly conforms.** Paths, fields, enums, error codes, status codes and WS close codes match `docs/DEVICE_CONTRACT.md`. The emulator drops config fields and trusts a stale version. The gaps are where the contract is silent (4xx batch, clock bounds, key rotation vs open socket, version ahead). | 0 | 2 | 3 | 3 |
| Happy path | **Pass.** Provisioning → PIN pairing/join → heartbeat → config pull/ack/304 → 8-slot matrix → popup/open → TAKEN_ON_TIME / TAKEN_LATE → localized ID/EN notifications all verified. One existing test depends on the time of day. | 0 | 0 | 0 | 2 |
| Sad paths | **Fail.** Idempotency, duplicates, outbox reconnect, auth errors, malformed input and DB outage recovery all hold. Failures: deadlock between telemetry and the rules engine, a poison-event outbox block, a device clock that can suppress or fabricate MISSED alerts, a revoked key that keeps its open socket, and no `lock_timeout`. | 2 | 3 | 4 | 2 |
| Scalability | **Fail at target.** Server-side heartbeat p50 is fine (5–26 ms ≤ 1,000 devices), but p95 is 1.5–2.6 s (target < 500 ms). Startup backlog gives 503s and 30 s stalls. From about 2,500 app sockets the single worker is CPU-bound (91–97% of one core), heartbeat p95 reaches 6–19 s, and with the shipped pool 894/5,000 app sockets failed to connect. | 0 | 4 | 9 | 1 |
| **Total** | | **2** | **9** | **16** | **8** |

The top three:
1. **C1 – One malformed event blocks the emulator outbox forever** (Verified). The backend rejects the whole batch with 422, the emulator treats any 4xx as "retry later", and the emulator itself can produce the bad value (`chime_count < 0` after the clock moves back). Every later dose event stays on the device, so caregivers get false MISSED alerts and taken doses are never recorded.
2. **C2 – A device clock that is far behind suppresses missed-dose alerts** (Verified). With `FOLLOW_DEVICE_CLOCK=true` (the default) and no bound on heartbeat `rtc_time`, a pillbox whose RTC reset to 2000-01-01 gets **zero** MISSED decisions for real doses and two bogus year-2000 dose rows.
3. **H1 – Deadlock between telemetry and the rules engine** (Verified, 6/6 runs). The device row is locked `FOR UPDATE`, while the rules engine's batch insert takes the FK's `FOR KEY SHARE`. Every collision aborts the whole rules-engine pass (all devices), and `decide_missed` is skipped for that tick. This is exactly the window-start moment (POPUP_ACTIVATED vs materialization).

## 2. Assumptions and environment

**Assumptions (from the brief; flagged where they look wrong)**
- Scale target: 1,000 devices online at once and 5,000 caregiver accounts, all holding `/ws/app`. ⚠️ *Looks inconsistent with the shipped config.* `db_pool_size=3`, `db_max_overflow=2` (`Backend/app/core/config.py:37-38`) is sized on purpose for a shared Supabase dev project, and Backend/CLAUDE.md mandates **one uvicorn worker**. The target needs an explicit deployment profile (see Q7).
- Intervals come from config/contract: heartbeat 15 s (`device_heartbeat_interval_seconds`), offline after 45 s, rules engine every 30 s, presence every 5 s, ack timeout 10 s.
- The contract defines **no telemetry interval** (events happen on dose actions, about 8 per device per day). The load script sends one 2-event batch per device every 4th heartbeat (60 s). That is about 100× real dose traffic, on purpose, as a stress margin.
- Pass criteria used: zero 5xx under nominal load; p95 < 500 ms for heartbeat/config/telemetry; no pool exhaustion; no unbounded memory growth; zero lost or duplicated events after reconnect.

**Environment**
| Item | Value |
|---|---|
| Machine | Linux 7.3.1 (CachyOS), 8 cores, 7 GB RAM, `ulimit -n` 1,048,576. Load client and server share the machine. |
| Database | Throwaway PostgreSQL 18.6 cluster in the session scratchpad (`initdb`, 127.0.0.1:55432, `max_connections=300`). DBs `pillcare_test` (pytest) and `pillcare_load_test` (live server). Never Supabase. A local DB has about 0.1 ms round trips, so remote-Supabase latency would be **worse** than measured here. |
| Backend venv | Python 3.12, fastapi 0.141.1, starlette 1.7.0, uvicorn 0.54.0, SQLAlchemy 2.1.1, asyncpg 0.31.0, pydantic 2.13.5, pydantic-settings 2.15.0, PyJWT 2.15.0, httpx 0.28.1, websockets 17.1, pytest 9.1.1, pytest-asyncio 1.4.0 (`uv pip list`) |
| SmartDevice venv | Python 3.14.8, requests 2.34.2, PySide6 6.11.2 |
| Server under load | `uvicorn app.main:app --workers 1`, background tasks on, `FOLLOW_DEVICE_CLOCK=true`, test-only JWT/provisioning values. Split-load runs at pool 3+2 (shipped) and 20+10; two earlier single-generator runs are kept only for server-side counts (§5). |

**Commands run**
```
cd Backend && TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/pillcare_test uv run pytest       # existing suite
cd SmartDevice && QT_QPA_PLATFORM=offscreen .venv/bin/pytest                                            # existing suite
cd Backend && uv run pytest -c pyproject.toml --rootdir=. ../docs/audits/scratch -p no:cacheprovider -s  # audit scenarios
uv run python ../docs/audits/scratch/setup_load_db.py --devices 1000                                    # seed 1,000 devices / 5,000 caregivers
.venv/bin/python ../docs/audits/scratch/load_test.py ... (pool 3+2, then 20+10)
.venv/bin/python ../docs/audits/scratch/db_outage.py ...
.venv/bin/python ../docs/audits/scratch/time_rules_pass.py
cd SmartDevice && PILLCARE_BACKEND_URL=http://127.0.0.1:8765 .venv/bin/python ../docs/audits/scratch/outbox_reconnect.py ...
```

**Phase 0: data flow (as built)**

```
Pillbox ──REST X-Device-Key──► /api/v1/devices/{code}/heartbeat|config|config-ack|telemetry
   │                              deps.get_authenticated_device → device_protocol.authenticate_device
   │                              (SELECT devices … FOR UPDATE, then SHA-256 + hmac.compare_digest)
   │                              ├ heartbeat  → presence.mark_seen, devices UPDATE, device_stocks UPSERT, LOW_BATTERY notify
   │                              ├ config     → schedules SELECT (304 if since_version ≥ config_version)
   │                              ├ config-ack → devices UPDATE (409 CONFIG_VERSION_UNKNOWN)
   │                              └ telemetry  → per event: device_events INSERT ON CONFLICT (claim) → schedules SELECT
   │                                             → telemetry_logs UPSERT (dose) → notifications INSERT (load_recipients)
   └──WS──► /ws/device/{code} (header or first-message auth; 4401 / 4000) heartbeat|ack|ping; commands from
            connection_manager (in-process dict) ← devices routes (alarm, calibrate, release, refill, schedule)
Background (lifespan, one leader per pass via pg_try_advisory_xact_lock):
   rules_engine (30 s): materialize_due_doses (all active schedules × lookback days, multi-row INSERT ON CONFLICT)
                        → decide_missed (PENDING past deadline FOR UPDATE SKIP LOCKED → MISSED + DOSE_MISSED notify)
   presence (5 s):      heartbeat timeout → OFFLINE; due DEVICE_OFFLINE notify
Notifications → Session after_commit hook → app_hub.publish → every /ws/app socket (in-process set)
dispatch_push (Expo/FCM) is a stub: no real push leaves the server.
```

| Device-facing route | Auth | Tables touched |
|---|---|---|
| POST heartbeat (REST/WS) | X-Device-Key, SHA-256, constant time | devices (lock+update), device_stocks, notifications (LOW_BATTERY, DEVICE_ONLINE) |
| GET config | same | devices (lock, last_heartbeat), schedules |
| POST config-ack | same | devices |
| POST telemetry | same | devices, device_events, schedules, telemetry_logs, notifications, user_elderly_roles/users/notification_preferences/elderly (recipients) |
| WS /ws/device | header or first message, 4401 | devices (no lock on auth), then as heartbeat |
| POST /admin/devices, rotate-secret | X-Provisioning-Token | devices |

## 3. Findings

Status: **V** = Verified (ran it, evidence attached); **R** = Reasoned-not-run (code reading). Paths are relative to the repo root. "Fix" is a proposal in words; nothing was applied.

### Critical

**C1 · Sad path / contract · One bad event blocks the device outbox forever — V**
- Expected: contract §2.4 says results are per event and all three statuses are final; §5.4 says retry only on timeout or 5xx. A 4xx batch is not covered (Q1).
- Actual:
  - Backend: any field error in one event (e.g. `chime_count: -1`, `ge=0` at `Backend/app/schemas/device_protocol.py:80`) fails the **whole batch** with `422 VALIDATION_ERROR`, and nothing is stored.
  - Emulator: `SmartDevice/smart_pillbox/core/sync.py:188-192` calls `raise_for_status()` and catches it like a network error, so the chunk is kept and resent first on every sync.
  - The emulator itself can create the value: `core/scheduler.py:253-256` computes `chime_count = int((now - activated_at)/2)`, which goes negative when the RTC is moved back while a chamber is ACTIVE (time_sync / "Sync Jam Nyata").
- Evidence:
  - `test_one_bad_event_poisons_the_whole_batch` → `poison batch: 422 stored=0`.
  - `outbox_reconnect.py` phase D (real emulator code against the live server): one `chime_count=-1` event + 5 good events → `flush results over 3 tries=[0, 0, 0] still_unsynced=6`.
- Fix:
  - Backend: validate per event (schema keeps `TelemetryEvent` loose, as already done for `event_type`), so a bad field becomes `rejected` with a reason.
  - Emulator: clamp `chime_count ≥ 0`; treat 422/413 as final-per-batch (or bisect), 401 as an identity problem, and only network/5xx as retry.
  - Contract: state the 4xx rule.

**C2 · Sad path / time · Device clock far behind suppresses MISSED alerts and fabricates doses — V**
- Expected: domain.md, dose lifecycle step 4 and the notifications section: PENDING past `window_end + tolerance` becomes MISSED and caregivers are notified. The 6 h `OFFLINE_MAX_WAIT` exists so "caregivers must still be told".
- Actual:
  - `FOLLOW_DEVICE_CLOCK=true` makes the rules engine judge "now" by `rtc_time + elapsed × rtc_speed` (`Backend/app/services/device_clock.py:21-32`).
  - Heartbeat `rtc_time` has no bound (`Backend/app/schemas/device_protocol.py:23`; `rtc_speed` ≤ 10,000 at `:25`).
  - A device reporting 2000-01-01 gets no MISSED decision for yesterday's real dose (also not after 6 h, because `can_decide_missed` uses the same device clock, `Backend/app/services/rules_engine.py:64-74`).
  - `materialize_due_doses` (`rules_engine.py:76-110`) shifts `not_before` by the skew and inserts doses dated 1999-12-31/2000-01-01.
- Evidence: `test_device_clock_behind_still_gets_missed_alert` → `bogus_year_2000_rows=2 real_missed=0`.
- Fix:
  - Clamp the followed device clock to `server_now ± MAX_DEVICE_CLOCK_SKEW` (new setting).
  - Always apply the `offline_max_wait` rule on **server** time.
  - Reject heartbeat `rtc_time` outside a window (or store it for the drift view only).
  - Raise a caregiver alert on large drift (Q2).

### High

**H1 · Sad path / DB · Deadlock between telemetry and the rules engine aborts whole passes — V**
- Expected: domain.md, dose lifecycle step 4 ("idempotent and safe with several workers") and Backend/CLAUDE.md (rules engine and presence).
- Actual: device routes lock `devices` with `FOR UPDATE` (`Backend/app/api/deps.py:85-93` → `services/device_protocol.py:44-46`, `presence.py:72-74`). `materialize_due_doses` inserts `telemetry_logs` rows whose FK check takes `FOR KEY SHARE` on the same device row, which conflicts with `FOR UPDATE`.
- How the deadlock forms:
  1. Telemetry for a dose (POPUP_ACTIVATED at window start) waits on the rules engine's uncommitted insert of the same `(schedule_id, scheduled_for)`.
  2. The rules engine waits on the device row lock.
- Consequences:
  - Postgres kills the rules-engine pass: one transaction for **all** devices.
  - `run_once` raises before `decide_missed`, so no MISSED decisions that tick (`rules_engine.py:144-153`).
  - At peak dose times (07:00 for many devices) this can repeat tick after tick.
- Evidence:
  - `test_device_alarm_timeout_races_rules_engine_one_missed_alert`, 6/6 runs: `telemetry -> 200; rules engine -> DBAPIError(... deadlock detected)`.
  - pg log: `while locking tuple (0,5) in relation "devices" … SELECT 1 FROM ONLY "public"."devices" x … FOR KEY SHARE OF x`.
- Fix:
  - Lock device rows with `FOR NO KEY UPDATE` (`with_for_update(key_share=True)`, verified to render that on SQLAlchemy 2.1.1). It still serializes device requests but no longer blocks FK checks.
  - Run `decide_missed` even if materialize fails, and catch/retry deadlocks.
  - Commit materialization in per-device chunks.

**H2 · Auth · Rotated (revoked) device key keeps its open WebSocket — V**
- Expected: contract §1 says "Lost the secret? Issue a new one"; a revoked key must stop working.
- Actual: `rotate_secret` (`Backend/app/services/provisioning.py:58-71`) changes the hash but never touches `connection_manager`. The socket authenticated with the old key keeps receiving commands and its heartbeats are processed. Those heartbeats can write `rtc_time`, and through C2 suppress alerts.
- Evidence: `test_rotated_key_closes_open_websocket` → `revoked-key socket still answers: heartbeat_ack` (REST correctly returns 401 for the old key).
- Fix: on rotate (and unpair), close the device socket with 4401 and drop pending commands. Optionally re-check the hash on WS heartbeats.

**H3 · Sad path / time · Device clock ahead marks future doses MISSED — V**
- Expected: domain.md, dose lifecycle step 4: MISSED only after the deadline.
- Actual: a device whose RTC is +1 day makes the rules engine materialize and decide doses whose real (server) window has not started yet, and DOSE_MISSED goes to caregivers.
- Evidence: `test_device_clock_ahead_does_not_miss_future_doses` → `MISSED doses whose server-time window is still in the future = 1`.
- Fix: same clamp as C2. Never decide MISSED before the server-time deadline.

**H4 · Scalability · Shipped pool (3+2) cannot carry the target; background loops starve — V**
- Expected: brief pass criteria (p95 < 500 ms, no pool exhaustion); contract §2.1 (offline after 45 s without a signal).
- Actual, run 1 (pool 3+2, 1 worker):
  - heartbeat p50 2.5 s / p95 17.2 s / max 30.3 s at 1,000 devices;
  - 96 × `503 SERVICE_UNAVAILABLE` at 100 devices (startup backlog, see H5);
  - 279 × 503 heartbeats + 93 × 503 telemetry at 1,000 devices + 1,000 app sockets;
  - 98 `QueuePool limit of size 3 overflow 2 reached` and 468 `db_unavailable` log lines;
  - 2 × `presence_sweep_failed` (the presence loop shares the request pool).
- Note: these run-1 latencies were later found to be inflated by the single-process load generator (§5). The **clean split run** with an independent probe (pool 3+2) shows:
  - server-side heartbeat p50 5–12 ms, p95 2.0–2.6 s at 500–1,000 devices;
  - a 30 s 503 during the startup backlog;
  - 699 `db_unavailable` and 3 `presence_sweep_failed`;
  - with app sockets, 503s on heartbeat and telemetry, and **894 of 5,000 `/ws/app` connections closed before `ready`** (auth needs a pooled connection).
- A 17–30 s heartbeat latency is within one step of the 45 s offline timeout.
- Evidence: §5 table, `docs/audits/scratch/results-pool-3-2.json`.
- Fix:
  - Make a deployment profile for the target (pool size, `db_pool_timeout_seconds`) and keep the dev profile small.
  - Give background loops their own small pool/engine.
  - Cut per-heartbeat round trips (H6, M3).
  - Raising the pool alone does not fix latency: run 2 (20+10) still had p95 1.5–2.6 s, and the event loop becomes the limit (H5, H6).

**H5 · Scalability / rules engine · Backlog pass is N+1 inside one transaction — V (observed) / R (attribution)**
- Expected: Backend/CLAUDE.md, Performance ("no N+1").
- Actual:
  - `decide_missed` loops over every due row and calls `notify_dose` → `load_recipients` (one query) + `notify` (one insert) per dose, all in **one** transaction holding a pooled connection and row locks (`rules_engine.py:113-141`, `doses.py` `notify_dose`).
  - The first pass on the seeded DB decided 9,996 MISSED doses and wrote 49,980 notifications. It ran while 100 devices were starting, which is when run 1 produced its 96 early 503s.
  - `materialize_due_doses` re-offers **every** active schedule × (lookback+1) days on every 30 s tick (`rules_engine.py:76-110`).
- Measured steady-state cost (`time_rules_pass.py`, local DB, 1,001 devices / 8,008 schedules, **0 rows created**):
  - `materialize_due_doses` 3,350 ms and 3,002 ms;
  - `decide_missed` 5–13 ms;
  - presence sweep 768 ms.
- That is about 3 s of mostly Python work (16,000 dose dicts + 1,000-row INSERT compiles) **on the event loop every 30 s**, which matches the roughly 30 s clusters of 1.3–2.6 s probe responses in the device-only phases.
- Fix:
  - Load recipients once per elderly (a dict cache inside the pass).
  - Insert notifications for many doses in one multi-row statement.
  - Commit in chunks.
  - Materialize only schedules whose next `window_start` fell in the last interval (or keep a per-schedule "materialized through" mark).

**H6 · Scalability / WebSocket · Every heartbeat fans out to every app socket — V (load) / R (cause)**
- Expected: brief (5,000 sockets); Backend/CLAUDE.md, Performance.
- Actual:
  - Every REST/WS heartbeat queues a device-status push (`services/device_protocol.py:109`), even when nothing changed.
  - `AppHub.publish` scans **all** connections and all changed devices per commit (`services/app_hub.py:78-95`). At 1,000 devices / 15 s that is about 67 publishes/s × 5,000 sockets.
  - Sends run without a timeout. A slow client holds its `send_lock`, and tasks accumulate in `_tasks` without a bound (`app_hub.py:97-110`).
  - Run 1: heartbeat p50 went 2.5 s → 4.2 s → 5.9 s → 9.5 s as app sockets went 0 → 1,000 → 2,500 → 5,000, with the DB pool unchanged. In the clean split runs, server CPU went from 40–63% (devices only) to 91–97% of one core at 2,500–5,000 sockets, with probe p95 6–19 s. This is the first CPU bottleneck.
- Fix:
  - Index connections by `elderly_id` (a dict of sets).
  - Push device status only when a field the app shows actually changed (battery bucket, doors, online state).
  - Add `asyncio.wait_for` around sends and drop/close slow sockets.

**H7 · Contract / emulator · Emulator ignores `is_refill_mode` and `timezone` from config — R (verified by reading)**
- Expected: contract §2.2 response; §3: "REST-only devices learn about the change from `config_update_available`".
- Actual: `SmartDevice/smart_pillbox/core/sync.py:273-279` applies only `schedules`; `is_refill_mode`, `timezone` and `chime_volume_level` are dropped.
- Consequence: a refill toggle made while the WebSocket is down never reaches the device. Opening a lid then logs `UNSCHEDULED_OPEN` (a CRITICAL alert) instead of `REFILL_MAINTENANCE`.
- Fix: apply all config fields atomically with the schedules.

**H8 · Sad path / config · A device reporting a version above the server never gets new config — V**
- Expected: contract §2.1 and §2.3. The server rejects an ack for a never-issued version (`409 CONFIG_VERSION_UNKNOWN`), so it should not trust the same claim in a heartbeat.
- Actual:
  - The heartbeat stores `config_version_applied=999` unchecked (`services/device_protocol.py:86-87`).
  - After a schedule change (server v2), `config_update_available=false` and `GET /config?since_version=999` returns `304`.
  - Schedules never reach the device until the server passes 999.
  - The emulator's fallback `config_version` is `"1"`, reset to `0` only on registration (`core/sync.py:139,200,217,267`).
  - Triggers: DB restore, env-override identity, emulator DB copied between machines.
- Evidence: `test_device_reporting_version_ahead_of_server_still_learns_new_config` → `stored applied=999; config-ack 999 -> 409 …; config_update_available=False config GET=304`.
- Fix:
  - Server: when `config_version_applied > config_version`, ignore it and answer `config_update_available=true`; return 200 for `since_version > latest`.
  - Emulator: reset the version when the identity changes.
  - Contract: specify this (Q6).

**H9 · Scalability · All realtime state is per process; target needs one Python process to hold 6,000 sockets — V (fds) / R**
- Expected: brief, single-process assumptions.
- Actual: `connection_manager`, `app_hub`, `pin_limiter`, `stock_cache` and `_pending` acks live in module globals (documented in Backend/README.md "Run"). Horizontal scale is impossible today. Commands from worker A cannot reach sockets on worker B, and the PIN limiter resets on restart.
- Run 1 reached 5,000 app + 1,000 device connections on one process (5,183 fds, RSS 117 → 531 MB); see §5. With pool 20+10 all 5,000 sockets opened, but connect p95 reached 20 s with one worker at 97% CPU.
- Fix: for now, state it as a hard deployment limit. Later, move the socket registry and command routing to a shared bus (Postgres LISTEN/NOTIFY or Redis pub/sub) and the PIN limiter to the DB.

### Medium

| ID | Area | Finding | Expected | Actual / evidence | Status | Fix |
|---|---|---|---|---|---|---|
| M1 | Sad path / time | A dose event with an absurd past `occurred_at` is accepted **and creates a dose row** | Contract §2.4: rejected covers bad timestamps (only future skew is defined) | `COMPARTMENT_OPENED` at 2000-01-01 → `accepted`, `telemetry_log_id` set, `dose rows created for year 2000 = 1` (`test_taken_event_with_far_past_clock…`); `match_dose` has no lower bound (`services/adherence.py:58-80`) | V | Add `TELEMETRY_MAX_PAST_SKEW` (e.g. lookback + max offline wait) and reject older events with a reason (Q3) |
| M2 | Auth / DoS | Device row is locked `FOR UPDATE` **before** the key is checked | Backend/CLAUDE.md Auth | `deps.py:85-93` → `find_device(lock=True)` then `verify_device_secret`; anyone who knows a printed `device_code` can make requests that queue on that device's row lock and take pooled connections | R | Authenticate without the lock, then lock (`FOR NO KEY UPDATE`) only after success |
| M3 | Scalability | Telemetry costs 3–6 round trips per event while holding the device lock | Backend/CLAUDE.md Performance | `services/telemetry.py:134-176`: claim INSERT, schedule SELECT, dose UPSERT, recipients SELECT, notification INSERT per event; a 500-event offline flush is about 2,000 round trips (≈ 40–100 s on a remote DB at 20–50 ms RTT) | R | Batch the claims (one multi-row INSERT … RETURNING), preload the device's schedules once per batch, cache recipients per batch |
| M4 | DB / index | Schedule edit "in progress" check cannot use the dose-key index | Backend/CLAUDE.md Performance | `services/schedules.py:136-141` lacks `scheduled_for IS NOT NULL`; `EXPLAIN` (seqscan off) uses `telemetry_logs_elderly_date_idx` on the second column only. With the predicate added: `Index Scan using telemetry_logs_dose_key_idx` | V | Add `TelemetryLog.scheduled_for.is_not(None)` |
| M5 | Scalability | Presence sweep is N+1 and shares the request pool | Backend/CLAUDE.md | `services/presence.py:161-185` runs `load_recipients` per offline device on every 5 s tick (24 h window); run 1 logged `presence_sweep_failed` ×2 (pool timeout) | V (failure) / R | Load recipients for all candidate elderly in one query; separate background pool |
| M6 | Access | `/ws/app` never re-checks the token or the role set | domain.md roles; API 404 for unrelated callers | `api/routes/ws.py:190-214`: token checked once; `elderly_ids` refreshed only on client `resubscribe`. A caregiver removed from an elderly keeps receiving that elderly's device pushes; an expired token never closes the socket | R | Close at token `exp`; refresh `elderly_ids` server-side when roles change (app_hub hook in caregiver revoke/leave/transfer) |
| M7 | Scalability (caregiver side) | `GET /elderly` is N+1 (4 queries per row) | Backend/CLAUDE.md Performance | `services/elderly.py:94-110` (sub-agent review) | R | Batch devices, doses and alert counts with `IN (…)` / `GROUP BY` |
| M8 | Scalability (caregiver side) | `GET /notifications` counts every row the user ever had, on each 5 s poll | same | `services/notification_feed.py:94-99`; the combined aggregate cannot use the partial unread index (sub-agent review) | R | Separate unread count (index-only on partial index), cap or drop `total`, add retention |
| M9 | DB | scrypt runs while a row lock / pooled connection is held | same | `services/device_management.py` `change_pin`, `join`, `calibrate`; `late_dose.release` (scrypt is correctly in `to_thread`, but the lock is held meanwhile) | R | Verify the PIN before taking the lock |
| M10 | Emulator | Heartbeat interval from the server is ignored | Contract §2.1 "every `heartbeat_interval_seconds`" | `SmartDevice/smart_pillbox/gui/main_window.py:158` uses `config.SYNC_INTERVAL_SECONDS = 15` (`config.py:68`) | R | Read the interval from heartbeat/welcome responses |
| M11 | Emulator | WS client: no close-code handling (4401 retries forever, 4000 flaps between two processes with the same identity), no jitter | Contract §3 close codes | `SmartDevice/smart_pillbox/core/ws_client.py:73-94` never reads `closeCode()`; backoff resets on connect | R | Stop on 4401 and surface it; back off with jitter on 4000 |
| M12 | Emulator | Heartbeat runs after the flush in the same worker; an exception in config apply skips the heartbeat | Contract §2.1 / §4 (45 s offline) | `core/sync.py:299` catches only `RequestException`; with 40 s request timeouts (`config.py:81`) a slow backend can delay the heartbeat past 45 s (sub-agent review) | R | Heartbeat first and independent of flush errors |
| M13 | Emulator | Outbox read is an unbounded `SELECT *` sliced to 200, every loop | — | `SmartDevice/smart_pillbox/db/database.py:248-251` (index only on `synced`) | R | `LIMIT ?` + index `(synced, occurred_at)` |
| M14 | Scalability | Unpaginated list endpoints | Backend/CLAUDE.md "every list endpoint paginated" | `GET /devices` (`api/routes/devices.py:54-59`), `GET /elderly/{id}/caregivers` (`api/routes/elderly.py:59-61`) | R | Add `PaginationDep` (contract change, propose in API list) |
| M15 | Scalability | Rules engine and presence share the request pool and run the full scan even when nothing is due | Backend/CLAUDE.md | see H5/M5; run 2 logged `rules_engine_pass_failed` with `QueuePool limit of size 20 overflow 10 reached` at 5,000 sockets | V | Separate engine; incremental scans |
| M16 | Sad path / DB | No `lock_timeout`: one stuck transaction takes the whole service down for 30 s | Brief: "graceful error, no hang" | `db_outage.py`: 10 device rows locked by an outside transaction. 5 requests for them filled the 5-connection pool and waited 30 s (`db_command_timeout_seconds`). **Every other device** and `/health/db` got `503` after 10 s (`db_pool_timeout_seconds`). After release: 200 in 11–23 ms | V | Set `lock_timeout` (new setting, e.g. 2–5 s) in `connect_args.server_settings`; fail fast with 503 for the locked device only |

### Low

| ID | Area | Finding | Evidence | Status | Fix |
|---|---|---|---|---|---|
| L1 | Tests | `test_bulk_save_applies_all_slots_with_one_config_version` depends on the wall clock: it failed at 12:28 WIB with `409 SLOT_IN_PROGRESS` because slot 2 is 12:00 + 30 min | `tests/test_roles_and_commands.py:145-164`; the same suite passed 52/52 at 13:05 WIB | V | Pin the device clock (`rtc_time`) or pick times relative to now |
| L2 | Tests | 3 SmartDevice tests are stale (already documented in SmartDevice/CLAUDE.md) | `test_database.py::test_log_event_and_sync_cycle`, `::test_update_schedule`, `test_scheduler.py::test_interact_ignored_when_not_active` | V | Update to current API |
| L3 | Hard-coding / l10n | Literals and Indonesian-only text in the backend | `db/session.py:94` `timeout=15`; `services/stock_cache.py:14` `REWRITE_SECONDS = 300`; `core/errors.py:130` `Retry-After: "5"`; resolution notes not localized by `interface_language`: `services/telemetry.py:346` "Jam pillbox dimundurkan…", `services/telemetry.py:453` "tercatat oleh sensor pillbox", `services/late_dose.py:166` "Dikonfirmasi dari notifikasi" | R | Move to Settings / message catalog |
| L4 | WS | Invalid WS heartbeat echoes the raw `input` back | `{'type': 'error', … 'input': 'abcabc…'}` (`test_ws_invalid_heartbeat_echo`); only the sender's own data, no internals | V | Send `loc`/`msg` only, like REST |
| L5 | WS | When a socket is replaced (4000), its pending commands are not failed; caller waits for the timeout (504) instead of 502 | `services/connection_manager.py:107-115` (early return when not current) | R | Fail pending commands of the replaced connection |
| L6 | DB | Redundant index `notifications_event_key_idx` (prefix of the unique `(event_key, user_id)`) | `migrations/0002…sql:75-76` | R | Drop in a migration |
| L7 | Emulator | Duplicate `trigger_alarm` with the same `command_id` is executed twice; config-ack `applied_at` uses the wall clock; invented `version` fallback field | `core/sync.py:276,286` | R | Dedupe by `command_id`; use RTC; drop the fallback |
| L8 | Emulator | `wifi_rssi_dbm` hard-coded `-50`; `rtc_backup_active` never sent | `core/sync.py:221` | R | Send real/simulated values |

### Checked and correct (no finding)
- Duplicate `event_id`, replayed and **concurrent**: 5 parallel copies → exactly 1 `accepted` + 4 `duplicate`; 1 TAKEN row, 1 notification (`test_replayed_and_concurrent_same_event_id_notifies_once`).
- Concurrent distinct OPENED events for one dose → 1 TAKEN, 1 notification, earliest open wins.
- Two devices with the same `event_id` → both accepted (unique per device, migration 0002:99).
- Overlapping rules-engine passes (4 at once) → no duplicate DOSE_MISSED (`(event_key, user_id)` unique + advisory lock + SKIP LOCKED).
- Device auth: missing / wrong / unknown code / UUID path / rotated key → identical `401 DEVICE_KEY_INVALID` bodies. Timing in-process: known-code median 12.01 ms vs unknown 11.88 ms (no measurable side channel; `verify_device_secret` compares against a dummy hash, `core/security.py:83-95`). Secrets are never logged (request log has path only, `app/main.py:69`).
- Malformed payloads: non-JSON, missing/ill-typed fields, 2 MB `batch_id`, bad door enum, 9 chambers, negative `since_version` → all `422 VALIDATION_ERROR` with `path`/`message` only; 501 events → `413 BATCH_TOO_LARGE`; unknown `event_type` → per-event `rejected`. No 5xx, no stack traces.
- Command to an offline device → `409 DEVICE_OFFLINE` / REST-only → `409 DEVICE_COMMAND_CHANNEL_UNAVAILABLE` (existing `tests/test_roles_and_commands.py`); all codes of contract §3 exist (`services/device_management.py:143-165`).
- Missed-dose notification exactly once per caregiver per dose (`DOSE_MISSED:<telemetry_log_id>` key), also when the device's ALARM_TIMEOUT and the rules engine both decide.
- Emulator: `event_id` generated at event time and reused on retry; rows marked synced by explicit id list; one sync worker at a time; heartbeat → flush order after reconnect; no secrets logged (sub-agent review, spot-checked).

## 4. Scenario matrix

| # | Scenario | Result | Evidence / reason |
|---|---|---|---|
| P2.0 | Existing Backend suite | **51 pass, 1 fail** | fail = L1 (wall-clock dependent); rerun at 13:05 WIB: **52 pass** |
| P2.0 | Existing SmartDevice suite | **25 pass, 3 fail** | the 3 known stale tests (L2) |
| P2.1 | Provisioning → pair (OWNER, PIN) → join (PEMANTAU, PIN) | Pass | `test_happy_path_end_to_end` |
| P2.2 | Heartbeat → `config_update_available` → config 200 → ack → 304 | Pass | same |
| P2.3 | 8-slot matrix: row A/B, BEFORE/AFTER_MEAL, MORNING..NIGHT | Pass | same (all 8 slots) |
| P2.4 | Popup → open on time → TAKEN_ON_TIME `delay 0`; open 14 min after window_end → TAKEN_LATE `delay 14` | Pass | same, journal day view |
| P2.5 | Caregivers notified, localized ID/EN by `interface_language` | Pass | same ("on time" / "tepat waktu") |
| P2.6 | Only one chamber active at a time | Pass (emulator, R) / N/A (backend) | emulator `_due` queue in `core/scheduler.py`; backend enforces it only via `SCHEDULE_TOO_CLOSE`, it has no runtime check |
| P2.7 | Live emulator GUI run | **Not run** | headless session; the emulator's sync code was driven directly instead (3.1) |
| 3.1 | Network drop → reconnect → outbox flush in order, no loss, no dupes | **Pass**, except the poison case (C1) | `outbox_reconnect.py`, 450 events. A offline: `flushed=0 still_unsynced=450`. B response lost after the server stored 200: `still_unsynced=450 server_rows=200`. C reconnect: `flushed=450 server_rows=450 distinct=450 match_local=True batches=3 oldest_first=True` |
| 3.2 | Duplicate `event_id` replay | Pass | see "Checked and correct" |
| 3.3 | Stale / newer `config_version` | Stale: Pass (304, re-pull). Newer: **Fail** (H8) | test + existing suite |
| 3.4 | Missing / wrong / revoked key, info leak, timing | REST: Pass. Open WS after revoke: **Fail** (H2) | tests |
| 3.5 | Clock skew behind / ahead / far-past events | **Fail** (C2, H3, M1) | tests |
| 3.6 | DB outage / pool exhaustion | Outage: **Pass**. Pool exhaustion: **Fail** (M16) | `db_outage.py`. Postgres stopped → heartbeats `503 SERVICE_UNAVAILABLE` in 7–10 ms, `/health/db` 503 "Database unreachable"; restarted → first heartbeat 200, no server restart. Held row locks → all devices 503 for 10–30 s |
| 3.7 | WebSocket disconnect storm, leaks, stale cleanup | App sockets: **Pass** (no leak). Device sockets: **Not run** | Each run closed 5,000 `/ws/app` sockets at once. On the same server process, fds went 5,183 → 220–260 and RSS 530 → about 300 MB in the next run (no leaked registry entries). The load used REST devices, so a device-WS reconnect storm and its `mark_offline` per disconnect were not exercised. Duplicate command delivery: the server never resends; the emulator does not dedupe (L7, R) |
| 3.8 | Malformed / oversized / wrong types / unknown types | Pass (REST) except one-bad-event (C1) | test |
| 3.9a | Concurrent events, same dose | Pass | test |
| 3.9b | Rules engine running twice / overlapping | Pass (no dupes) | test |
| 3.9c | Rules engine vs device timeout, same dose | **Fail** (deadlock, H1) | test, 6/6 |
| 3.9d | Missed-dose notification exactly once | Pass | tests |
| 3.9e | Command to offline device | Pass | existing suite |
| 3.9f | Two devices, same `event_id` | Pass | test |

## 5. Load test results

**Method.**
- Seed: `setup_load_db.py` (1,001 devices, 5,005 caregivers, 5 per elderly, 8 schedules per device, paired 3 days ago).
- Server: one uvicorn worker with background tasks on.
- Load: `run_split.sh` runs 4 generator processes (250 devices and 1,250 app sockets each) plus an independent `curl` probe (`probe.sh`, 1 heartbeat/s from its own process).
- Steps: devices 100 → 500 → 1,000 (60 s each), then app sockets 1,000 → 2,500 → 5,000 (45 s each) while all devices keep running.
- Devices send REST heartbeats at the server's `heartbeat_interval_seconds` (15 s), config pull + ack when told, and a 2-event telemetry batch every 60 s.
- Each run starts from a freshly seeded DB, so the first rules-engine pass backfills about 10,000 MISSED doses.

> ⚠️ The first two runs (`results-pool-3-2.json`, `results-pool-20-10.json`) used **one** generator process. An independent probe during a repeat showed the server answering in p50 11 ms while that generator reported p50 2.9 s: the generator's event loop (≈ 84% CPU) was the bottleneck. Those latencies are **discarded**; only their server-side counts (503s, pool errors, fds, RSS) are used above. The tables below are the clean split runs.

**Independent probe, server-side heartbeat latency (ms)**

| Phase | Pool 3+2 (shipped): p50 / p95 / max | non-200 | Pool 20+10: p50 / p95 / max | non-200 |
|---|---|---|---|---|
| 100 devices (startup backlog) | 5 / 30,035 / 30,035 | 1 × 503 | 10 / 6,778 / 30,029 | 1 × 503 |
| 500 devices | 5 / 2,566 / 3,228 | 0 | 5 / 1,761 / 2,609 | 0 |
| 1,000 devices | 12 / 1,971 / 5,872 | 0 | 26 / 1,551 / 2,599 | 0 |
| 1,000 dev + 1,000 app WS | 8 / 5,828 / 10,765 | 1 × 503 | 37 / 6,133 / 11,553 | 0 |
| 1,000 dev + 2,500 app WS | 607 / 5,903 / 5,903 | 0 | 7,779 / 11,892 / 11,892 | 0 |
| 1,000 dev + 5,000 app WS | 403 / 11,077 / 11,077 | 1 × 503 | 1,611 / 18,589 / 18,589 | 0 |

**Generators, all devices (worst process p50 / p95 in ms; summed status counts)**

| Phase | Pool 3+2: heartbeat | telemetry | Pool 20+10: heartbeat | telemetry |
|---|---|---|---|---|
| 100 devices | 8,006 / 10,052; **122 × 503** of 322 | 542 / 828 | 9,716 / 30,028; **99 × 503** of 243 | — |
| 500 devices | 15 / 3,523 | 1,076 / 2,281 | 17 / 2,012 | 642 / 3,312 |
| 1,000 devices | 350 / 5,336 | 1,163 / 2,458 | 41 / 2,917 | 501 / 3,054 |
| + 1,000 app WS | 148 / 9,801; 95 × 503, 36 ReadError | 3,787 / 10,707; 37 × 503 | 385 / 6,776; 3 × 503 | 624 / 5,990 |
| + 2,500 app WS | 3,803 / 9,757; 62 × 503 | 2,370 / 8,251; 3 × 503 | 2,418 / 17,092; 147 × 503, 44 ReadError | 769 / 10,263; 26 × 503 |
| + 5,000 app WS | 1,393 / 10,741; **358 × 503**, 33 ReadError | 1,034 / 10,097; 19 × 503 | 881 / 17,286 | 780 / 3,133 |

config / config-ack at 1,000 devices: p95 714 / 762 ms (3+2) and 622 / 235 ms (20+10).

**App sockets (`/ws/app`)**

| Step | Pool 3+2: opened / failed (connect p95) | Pool 20+10: opened / failed (connect p95) |
|---|---|---|
| 1,000 | 866 / 134 `ConnectionClosedError` (6.9 s) | 1,000 / 0 (14.8 s) |
| 2,500 | +1,464 / 36 (8.4 s) | +1,500 / 0 (8.1 s) |
| 5,000 | +1,776 / **724** (10.1 s) | +2,500 / 0 (19.9 s) |
| **Total reached** | **4,106 / 5,000** | **5,000 / 5,000** |

**Server resources** (sampled every 5 s; `/proc/<pid>`, `pg_stat_activity`)

| Phase | 3+2: CPU (one core) · RSS · fds · DB conns · lock waits | 20+10: same |
|---|---|---|
| 100 devices | 62% · 126→170 MB · 91 · 5 · 4 | 68% · 127→175 MB · 138 · 30 · 29 |
| 500 devices | 42% · 171 MB · 248 · 5 · 0 | 40% · 178 MB · 186 · 30 · 0 |
| 1,000 devices | 63% · 172 MB · 391 · 5 · 4 | 61% · 178 MB · 279 · 30 · 26 |
| + 1,000 app WS | 70% · 261 MB · 1,389 · 5 · 0 | 77% · 244 MB · 1,437 · 30 · 29 |
| + 2,500 app WS | 93% · 363 MB · 2,913 · 5 · 1 | 96% · 366 MB · 3,003 · 30 · 0 |
| + 5,000 app WS | 91% · 495 MB · 4,539 · 5 · 0 | 97% · 539 MB · 5,267 · 30 · 1 |

Server log per run: 3+2 → 699 `db_unavailable`, 3 `presence_sweep_failed`; 20+10 → 277 `db_unavailable`, 1 `presence_sweep_failed`, 1 `rules_engine_pass_failed` (pool timeout). A 1,000-device steady-state burst sampled with `lock_sampler.py` showed **no** lock waits, so the lock-wait peaks above coincide with the startup backlog / rules-engine passes.

**Bottlenecks, in the order they appear**
1. **Startup or backlog rules-engine pass** (H5): about 10,000 MISSED decisions with per-dose recipient queries in one transaction. At **100 devices** this already gives 503s and a 30 s stall with either pool size. In production the same happens after any outage longer than one dose window.
2. **Event-loop stalls from the 30 s rules-engine scan** (H5): 3.0–3.4 s of Python per pass even with nothing to create. From **500 devices** the device-only p95 is 1.5–2.6 s against the 500 ms target. A bigger pool does not help.
3. **DB pool 3+2** (H4): with app sockets, 503s on heartbeat/telemetry and **18% of app sockets failing to connect** at the 5,000 step.
4. **Single worker CPU** (H6, H9): from **2,500 app sockets** the process sits at 93–97% of one core, and probe p95 reaches 6–19 s. That is close to the 45 s offline timeout under a remote DB.
- **Largest level reached:** 1,000 devices + 5,000 app sockets with zero socket failures (pool 20+10). Latency criteria were not met at any step above 100 devices.
- **Memory:** about 80 KB per app socket, linear (126 → 539 MB). It was released after the sockets closed (fds back to about 220). No unbounded growth was seen in 6-minute runs (no soak test).
- Raw data: `docs/audits/scratch/results-pool3-2-p*.json`, `results-pool20-10-p*.json`; probe and server logs were kept in the session scratchpad only.

## 6. Not verified

- **Real Supabase / transaction pooler (6543)** latency and its client limits: everything ran on a local Postgres 18.6. Production round trips are 20–100× slower, so all latencies here are optimistic.
- **Multi-worker or multi-instance behavior**: not run. It is documented as unsupported (H9).
- **Emulator GUI (PySide6) end to end**: not launched. The outbox scenario drove `smart_pillbox.core.sync` + `db.database` directly with `requests`, using the SmartDevice venv only for imports (no packages installed). WS client behavior (M11, M12, L7) and refill handling (H7) are code reading only.
- **Real push delivery**: `dispatch_push` is a stub (`services/notifications.py:280`). "Caregiver notified" means a DB row + `/ws/app` push, not a phone notification.
- **Long-duration memory growth**: runs lasted about 6 minutes each. RSS growth tracked socket count (§5), but no hours-long soak was run.
- **Load generator limits**: client and server shared 8 cores. Latencies include client-side scheduling; the comparison between runs is the reliable part.
- **Contract source of truth**: the API list spreadsheet and the ERD (dbdiagram) were not opened. Contract checks used `docs/DEVICE_CONTRACT.md`, `docs/ai/*.md` and code.
- Sub-agent review items marked R (M7, M8, M9, M12, M13, L7) were spot-checked, not all line-verified. Some line numbers in its raw notes were wrong and were corrected here from `grep`.

**Mobile/BACKEND_HANDOFF.md gaps (not provided by Backend today)**: §1 rate limit on `/pairing/scan` and `POST /devices`; §2 `elderly_name_if_owned` leaked to any signed-in user (`services/device_management.py:212`); §3 `DELETE /notifications?device_id=`; §4 `GET /notifications?device_id=` with a filtered `unread_count`; §5 `DELETE /devices/{id}?purge_my_notifications=true`; §6 per-device membership (`DELETE /devices/{id}/membership`); §7 `POST /admin/devices/{code}/reset`.

## 7. Questions for me (conflicts and contract ambiguities)

1. **Q1 (C1)**: contract §2.4/§5.4 says what to do on timeout/5xx and with per-event results, but not on a **4xx batch** (422/413/401). Should a field error be per-event `rejected` (my proposal), or should devices drop or bisect a 422 batch?
2. **Q2 (C2/H3)**: contract §2.1 and §6 row 4 make the backend **follow the device clock** (by design, for the lab clock). domain.md says missed doses must always reach caregivers. Which wins when the device clock is absurd? Proposal: follow it only within a bounded skew, and always apply the 6 h rule on server time.
3. **Q3 (M1)**: should telemetry reject events older than some bound (`occurred_at` too far in the past), symmetric to the 7-day future rule?
4. **Q4**: **Known CONFLICT, still open**. `notification_preferences.notify_on_taken` defaults to FALSE in migration 0001, but `services/notifications.py:33-40` treats a missing row as TRUE (architecture.md conflict 6). Which is intended?
5. **Q5 (H2)**: should `rotate-secret` (and unpair) close the device's open WebSocket? The contract is silent.
6. **Q6 (H8)**: what should the server do when a heartbeat reports `config_version_applied` greater than `latest_config_version`?
7. **Q7 (H4/H9)**: is the 1,000 devices / 5,000 sockets target meant for one uvicorn worker on Supabase's pooler? Backend/CLAUDE.md requires one worker, and the default pool is 5. Please confirm the deployment profile (pool size, Supabase plan limits) before I size fixes.
8. **Q8**: domain.md says "Only one chamber active at a time" as a hardware constraint. The backend enforces it only through schedule spacing (`SCHEDULE_TOO_CLOSE`) and has no runtime check (e.g. `release_slot` while another chamber is up is refused only by the device). Is that enough?

## 8. Proposed fix plan (ordered by severity, one commit per scope)

Proposals only; nothing is applied until you approve. Each commit is one scope, with the tests it adds. Commits 2, 3, 5 and 6 need your answers to Q2/Q3, Q1, Q5 and Q6 first.

| # | Commit | Fixes | Tests it adds or updates |
|---|---|---|---|
| 1 | `fix(backend): lock device rows for no key update and check the key before locking` | H1, M2 | Rules engine vs ALARM_TIMEOUT race: no deadlock and pass completes (port `test_device_alarm_timeout_races_rules_engine_one_missed_alert`). A wrong-key request does not block a concurrent valid heartbeat |
| 2 | `fix(backend): bound the followed device clock and reject far-past events` | C2, H3, M1 (after Q2, Q3) | Clock behind → real dose MISSED, no year-2000 rows. Clock ahead → no future MISSED. Far-past OPENED → `rejected` with a reason. New settings in `config.py` + `.env.example` |
| 3 | `fix(backend): reject invalid telemetry fields per event instead of the whole batch` | C1, backend side (after Q1) | One bad field + good events → 200, good `accepted`, bad `rejected` |
| 4 | `fix(pillbox): treat 4xx telemetry answers as final and clamp chime_count` | C1, device side | Sync with mocked 422/413/401/5xx responses (only network/5xx keep events). Scheduler: clock set back while ACTIVE gives `chime_count ≥ 0` |
| 5 | `fix(backend): close the device socket when its secret is rotated or unpaired` | H2 (after Q5) | Rotate → open socket closed with 4401; pending commands fail with 502 |
| 6 | `fix(backend): ignore an applied config version above the latest` | H8, server side (after Q6) | Heartbeat applied=999 → `config_update_available` true; `since_version` > latest → 200 |
| 7 | `fix(pillbox): apply refill mode and timezone from config and follow the server heartbeat interval` | H7, H8 device side, M10 | Config apply test (refill/timezone persisted atomically); version reset on identity change; interval taken from the response |
| 8 | `perf(backend): batch recipients and notifications and materialize only newly due doses` | H5, M5, M15 | Existing rules-engine idempotency tests stay green. Query-count assertion for a 100-dose pass. Pass time on a 1,000-device seed (scratch script) |
| 9 | `perf(backend): give background tasks their own pool and set a lock timeout` | H4, M16 | Locked row → that device 503 within `lock_timeout`, other devices 200 |
| 10 | `perf(backend): index app sockets by elderly and push device status only on change` | H6, M6 (role refresh) | `test_app_push`: unchanged heartbeat sends nothing; revoked caregiver stops receiving; slow socket dropped after the send timeout |
| 11 | `perf(backend): batch telemetry claims and preload schedules per batch` | M3 | 500-event flush: same results, bounded query count |
| 12 | `perf(backend): use the dose-key index for in-progress checks and batch the elderly list` | M4, M7, M8, M9 | EXPLAIN-based test or query-count tests for `GET /elderly`, `/notifications` |
| 13 | `fix(pillbox): handle websocket close codes with jittered backoff and decouple heartbeat from flush` | M11, M12, M13, L7, L8 | ws_client close 4401 stops retrying; heartbeat still sent when config apply raises; outbox query uses LIMIT |
| 14 | `refactor(backend): move remaining literals and notes into settings and the message catalog` | L3, L4, L5 | Notes localized by `interface_language`; WS validation error has no `input` |
| 15 | `fix(db): drop the redundant notifications event_key index` | L6 | Migration 0007 applies on the test DB (suite run) |
| 16 | `test(backend): pin the device clock in the bulk schedule save test` | L1 | The test itself, run at any hour |
| 17 | `test(pillbox): update the three stale database and scheduler tests` | L2 | SmartDevice suite fully green |
| 18 | `feat(api)!: paginate the device and caregiver lists` | M14 | Contract change: propose in the API list first; app update needed |
| 19 | `docs(api): specify 4xx batches, clock bounds, key rotation and version-ahead in the device contract` | C1, C2, H2, H8 (record Q1, Q2, Q5, Q6 answers) | — |

H9 (single process) is a deployment decision (Q7), not a single commit.

## 9. Fix status (working tree, not committed; 2026-11-03)

Decisions taken (Q1, Q2/Q3, Q5, Q6): per-event rejection of invalid fields; device clock followed only within ±7 days, 6 h rule on server time, dose/door events older than 7 days rejected; rotate-secret closes the socket with 4401; a config version above the latest is stale (re-sync). Recorded in `docs/DEVICE_CONTRACT.md`.

| Finding | Status | Test (all run, all pass) |
|---|---|---|
| C1 | Fixed: backend per-event rejection; emulator treats final 4xx as final, 413 re-chunks, `chime_count` ≥ 0 | `test_one_invalid_event_does_not_reject_the_batch`, `SmartDevice/tests/test_sync.py`, scheduler test; `outbox_reconnect.py` D: `[6, 0, 0]` |
| C2, H3, M1 | Fixed within the chosen bound (a clock ≤ 7 days ahead is still followed, by design) | 3 clock tests in `test_rules_engine.py`, `test_dose_event_far_in_the_past_is_rejected` |
| H1 | Fixed (`FOR NO KEY UPDATE`; decide_missed runs even if materialization fails) | `test_device_timeout_racing_the_rules_engine_does_not_deadlock` |
| H2 | Fixed | `tests/test_device_socket.py` |
| H4, M15 | Fixed (separate background pool); pool size for the target is still Q7 | load runs |
| H5 | Fixed: steady pass 2,554 → 630 ms; backlog of 8,000 doses: materialize 3.4 → 1.0 s, decide 36.4 → 5.7 s; loop yields every 500 schedules | rules tests + `time_rules_pass.py` |
| H6 | Fixed (indexed sockets, throttled unchanged status, send timeout) | 3 tests in `test_app_push.py` |
| H7, M10–M13, L2, L7, L8 | Fixed in the emulator | `test_sync.py`, `test_ws_client.py`, updated stale tests (44/44 pass) |
| H8 | Fixed (server; the emulator re-syncs on its own) | `test_device_reporting_an_unknown_newer_version_resyncs` |
| H9 | **Open**: single process by design; needs a deployment decision (Q7) | — |
| M2 | Fixed (key checked before the row lock; costs one extra round trip per device request, measured as within run-to-run noise) | `test_wrong_device_key_does_not_wait_for_the_row_lock` |
| M3 | Fixed (claims, re-send lookup, schedules and recipients once per batch) | `test_batch_cost_does_not_grow_per_event` |
| M4 | Fixed | EXPLAIN (§3) |
| M5 | Fixed | existing presence paths |
| M6 | Fixed (close at token expiry; roles re-read after commit) | 2 tests in `test_app_push.py` |
| M7 | Fixed (3 queries per page instead of 4 per elderly: 15 → 7 statements for 3 elderly) | `tests/test_elderly_list.py` |
| M8 | Improved (two index-backed scalar subqueries, one round trip: 16 → 8 ms at 50k rows); retention / capping `total` still needs a product + API list decision | `test_feed_counts_follow_the_tab` |
| M9 | Fixed (no lock or transaction during scrypt) | `test_owner_changes_the_device_pin` + existing PIN tests |
| M14 | **Open**: pagination of `GET /devices` and caregivers changes the API list (needs approval) | — |
| M16 | Fixed (`DB_LOCK_TIMEOUT_MS`, not sent through the transaction pooler: set it on the DB role there; not verified on Supabase) | `test_request_stuck_on_a_row_lock_fails_fast_with_503` |
| L1, L3, L4, L5 | Fixed (clock pinned; literals in settings; notes localized ID/EN per recipient; no input echo; replaced socket fails its commands) | tests in `test_roles_and_commands.py`, `test_rules_engine.py`, `test_device_socket.py` |
| L6 | **Open**: dropping an index is destructive and needs explicit approval (`.claude/rules/database-ownership.md`) | — |

**Load after the fixes** (split generator + independent probe, local DB, same machine; runs vary noticeably):

| Phase | Probe p50 / p95 (ms), pool 3+2 | Probe p50 / p95 (ms), pool 20+10 |
|---|---|---|
| 100 devices | 9 / 720 (no 503; before: 30 s stall + 503) | 8 / 738 |
| 1,000 devices | 11 / 2,768 | 21 / 1,331 |
| + 5,000 app sockets | 17 / 3,804; 4,229 of 5,000 sockets in one run, 4,898 in another | 1,827 / 8,200; 4,965 of 5,000 sockets |

Still not met: p95 < 500 ms above about 100 devices, and the single worker reaches 90–97% of one core from 2,500 app sockets. Both need the deployment decision (Q7: pool size on Supabase, more than one worker, which requires moving socket and command state out of process, H9).
