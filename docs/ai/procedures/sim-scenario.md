# Procedure: define and run an emulator scenario

A scenario is data plus assertions, so demos and tests are repeatable. Automated scenarios are pytest tests in `SmartDevice/tests/` (create a `scenarios/` folder there only if data files are needed). For backend-side checks, `Backend/scripts/fake_device.py` is a scriptable device client.

Scenarios to cover: on-time dose, late dose, missed dose, unscheduled open, offline then flush, duplicate telemetry, config update while a chamber is active, remote alarm and ack, power loss with backup battery, clock drift and `time_sync`.

1. Describe the setup: device timezone, schedules (slot, window, tolerance, days), starting stock, battery, network state.
2. Describe a timeline using the simulated RTC (`smart_pillbox/core/rtc.py`: speed, jumps) and the scheduler/database APIs used by the existing tests (`tests/test_scheduler.py`), with actions such as opening a compartment or going offline. Read those tests before writing new ones; do not guess method names.
3. Describe expectations: events written to the outbox (type, slot, order), what the backend should answer (`accepted`, `duplicate`, `rejected`), and the resulting dose status (`PENDING -> TAKEN | MISSED`, derived `TAKEN_ON_TIME` / `TAKEN_LATE`).
4. Run with `.venv/bin/pytest` in `SmartDevice/` (no backend needed). Run against the real Backend only on a development database.
5. Report which expectations passed. If you did not run it, say so.
