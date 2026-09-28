# Smart Pillbox — Device Simulator

Python + PySide6 + SQLite simulation of the Smart Pillbox hardware, standing
in for the physical device per the CE739L proposal (Informatics group, no
physical hardware built).

## What this simulates

- 8 compartments in a 2×4 grid (Sebelum/Sesudah Makan × Pagi/Siang/Sore/Malam)
- Pop-up + Breathing LED (yellow = before meal, blue = after meal)
- Reed Switch open/close validation, abstracted into one
  "Ambil Obat (Buka → Tutup)" button per active compartment
- **Single Active Chamber** constraint — a second due compartment queues
  until the first is closed or marked MISSED
- A Rules Engine that flags **MISSED** once the tolerance window expires
- A simulated RTC with adjustable speed and a "Jump +1 hour" control, so a
  demo doesn't require waiting real hours between meal times
- An offline-first local SQLite event log that doubles as the telemetry
  queue — sync attempts fail gracefully (and just keep buffering) until the
  FastAPI backend exists

## Run it

```bash
pip install -r requirements.txt
python main.py
```

A fresh run creates `pillbox_local.db` next to this file, seeded with a
default schedule (07:00/12:00/17:00/20:00 before meals, +30 min after).
Edit `_DEFAULT_SCHEDULE` in `smart_pillbox/db/database.py` or use
`Database.update_schedule()` to change it.

## Run the tests

```bash
pytest
```

Tests cover the scheduler (activation, MISSED detection, single-active-chamber
queueing), the RTC, and the SQLite layer — all pure Python, no GUI/display
needed, so they run headless in CI too.

## Known simplifications (documented, not hidden)

- `interact()` logs `DOOR_OPEN` → `DOOR_CLOSE` → `TAKEN` from a single button
  press rather than two separate physical transitions — acceptable for a
  simulator, but note it if a reviewer asks how the real Reed Switch flow maps
  to this code.
- No actual chime audio (`QSoundEffect`) is wired up yet — the UI shows a 🔔
  indicator text instead. Add an asset + `QSoundEffect` in
  `compartment_widget.py` if audio is required for the demo.
- `sync.flush_pending_events()` runs on the GUI thread via `QTimer`, blocking
  briefly (bounded by `SYNC_HTTP_TIMEOUT_SECONDS`) if the backend is
  unreachable. Fine for a 3-second timeout in a demo; move to a `QThread`
  before this becomes a real device app.
- `BACKEND_TELEMETRY_URL` in `config.py` is a placeholder — update it once
  the FastAPI endpoint spec is finalized so the JSON payload shape matches.
