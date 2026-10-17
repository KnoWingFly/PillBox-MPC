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
- A Rules Engine that flags **MISSED** once the tolerance window expires.
  A dose window is `schedule_time` to `schedule_time + tolerance`, the same
  window the backend uses. A chamber only pops up inside it. If the simulator
  starts, or the clock jumps, after a window has closed, that dose shows
  MISSED without ringing instead of popping up hours late.
- Today's TAKEN/MISSED states are rebuilt from the local event log at
  start-up, at midnight and when the clock is set back, so a restart never
  re-pops a dose that was already taken.
- A simulated RTC with adjustable speed, "+1 Hour" and "Jadwal Berikutnya"
  (jump to 5 s before the next pop-up) controls, so a demo doesn't require
  waiting real hours between meal times. Every clock change is sent in a
  heartbeat right away (`rtc_time` + `rtc_speed`). The backend and the mobile
  app then follow the pillbox clock ("Jam Pillbox" on the Perangkat tab).
  "Sync Jam Nyata" goes back to real time at 1x.
- A chime that repeats every `CHIME_REPEAT_SECONDS` while a chamber is popped
  up (see "Chime sound" below)
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
- `sync.flush_pending_events()` runs on the GUI thread via `QTimer`, blocking
  briefly (bounded by `SYNC_HTTP_TIMEOUT_SECONDS`) if the backend is
  unreachable. Fine for a 3-second timeout in a demo; move to a `QThread`
  before this becomes a real device app.
- `BACKEND_TELEMETRY_URL` in `config.py` is a placeholder — update it once
  the FastAPI endpoint spec is finalized so the JSON payload shape matches.

## Chime sound

Put the sound at `smart_pillbox/assets/chime.wav`, or point
`PILLCARE_CHIME_FILE` at another file. It is played with `QSoundEffect`, which
only plays **uncompressed PCM WAV**:

- `.wav`, PCM (not MP3/OGG/AAC inside a WAV), 16-bit
- 44.1 kHz or 48 kHz, mono or stereo
- about 1-3 seconds; it repeats every `CHIME_REPEAT_SECONDS` (config.py)

Without a usable file the simulator falls back to the system beep, which is
often silent on Linux. To convert another file:
`ffmpeg -i chime.mp3 -ac 1 -ar 44100 -c:a pcm_s16le smart_pillbox/assets/chime.wav`

## Connecting to the PillCare backend

1. Start the backend (`Backend/README.md`). It must have `PROVISIONING_TOKEN` set in `Backend/.env`.
2. Run the emulator. In the **Koneksi Server** panel (bottom right), press **Daftarkan Perangkat**.
   The emulator reads `PROVISIONING_TOKEN` from `PILLCARE_PROVISIONING_TOKEN`, `SmartDevice/.env`
   or `../Backend/.env` (asks you to paste it if none is found), registers itself with the backend,
   stores its own device code + secret in `pillbox_local.db`, and copies the code to the clipboard.
3. In the mobile app, the dashboard shows **Hubungkan Pillbox**: type the code, choose a 4-digit PIN,
   press **Hubungkan**. The panel switches to "Terpasang ke aplikasi" on the next heartbeat (≤ 15 s).
4. Schedules saved in the app are pulled on the next heartbeat and applied live.

Backend elsewhere? Set `PILLCARE_BACKEND_URL=http://<host>:8000` before starting the emulator.
"Reset Identitas" forgets the code/secret (e.g. after the backend database was reset).
Device ↔ backend protocol: `docs/DEVICE_CONTRACT.md`.
