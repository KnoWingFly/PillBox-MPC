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
python -m venv .venv                    # once
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py                # the default pillbox
.venv/bin/python main.py --profile pb2  # another, independent pillbox (see below)
```

`requirements.txt` includes `segno` (pure-Python QR generator, no Pillow needed) for the
pairing QR. A fresh run creates `pillbox_local.db` next to this file, seeded with a
default schedule (07:00/12:00/17:00/20:00 before meals, +30 min after).
Edit `_DEFAULT_SCHEDULE` in `smart_pillbox/db/database.py` or use
`Database.update_schedule()` to change it.

## Run the tests

```bash
.venv/bin/pytest
```

Tests cover the scheduler (activation, MISSED detection, single-active-chamber
queueing), the RTC, and the SQLite layer — all pure Python, no GUI/display
needed, so they run headless in CI too.

## Known simplifications (documented, not hidden)

- `interact()` logs `DOOR_OPEN` → `DOOR_CLOSE` → `TAKEN` from a single button
  press rather than two separate physical transitions — acceptable for a
  simulator, but note it if a reviewer asks how the real Reed Switch flow maps
  to this code.
- Sync (`SyncWorker`) and registration (`RegisterWorker`) run on `QThreadPool` workers, so a slow
  or unreachable backend never freezes the GUI; one sync runs at a time.

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
3. The panel shows the code and a **QR code** of it (click the QR to enlarge it). The QR holds only
   the public device code, never the secret. In the mobile app open **Perangkat → Tambah pillbox**
   (or the "Belum ada pillbox" screen on a fresh account), press **Pindai QR** or type the code,
   then choose a 4-digit PIN, a name and the elderly profile.
   The panel switches to "Terpasang ke aplikasi" on the next heartbeat (≤ 15 s).
4. Schedules saved in the app are pulled on the next heartbeat and applied live.

Backend elsewhere? Set `PILLCARE_BACKEND_URL=http://<host>:8000` before starting the emulator.
"Reset Identitas" forgets the code/secret (e.g. after the backend database was reset).
Device ↔ backend protocol: `docs/DEVICE_CONTRACT.md`.

## Several pillboxes at once

Each pillbox is its own **process** with its own **profile**: its own SQLite database, so its own
device code + secret, schedules, event log and sync loop.

- `python main.py` is the `default` profile (`pillbox_local.db` next to `main.py`, as before).
- `python main.py --profile pb2` uses `profiles/pb2/pillbox_local.db` (`profiles/` is git-ignored).
- **Tambah Pillbox Virtual** (status bar, bottom right) opens the next free profile of
  `default`, `pb2`, `pb3`, `pb4` in a new window: at most 4 at once.
- A profile can run only once (a `QLockFile` per profile); starting it twice shows
  "Pillbox virtual '…' sudah terbuka". A crashed window's lock is released automatically.
- **Reset Identitas** only touches that window's own database.
- `PILLCARE_DEVICE_CODE` / `PILLCARE_DEVICE_KEY` apply to the `default` profile only, so an
  exported value can never give two pillboxes the same identity.

Why processes instead of several windows in one process: each window then has its own database
connection, thread pool, WebSocket and sound effect, and a crash or reset in one cannot affect
another. The backend tells pillboxes apart by device code (each `register` creates a new one).

### Two-pillbox demo

1. Start the backend, then `.venv/bin/python main.py`. Press **Daftarkan Perangkat** (pillbox A).
2. Press **Tambah Pillbox Virtual**. A second window titled `[pb2]` opens; press
   **Daftarkan Perangkat** there too (pillbox B, a different code).
3. In the app: **Perangkat → Tambah pillbox → Pindai QR**, scan A's QR, PIN `1234`,
   name "Kamar Ibu". Repeat for B as "Kamar Ayah". The app's pillbox switcher shows both.
4. Within 15 s both windows show "Terpasang ke aplikasi".
5. Select "Kamar Ayah" in the app and save a schedule for a slot a few minutes ahead.
   Only the `[pb2]` window applies it (status bar: "Jadwal baru dari aplikasi diterapkan").
6. Let the dose pop up in `[pb2]` and take it (or let it go missed). The notification
   appears in the app under "Kamar Ayah" only; switch to "Kamar Ibu" and it is not there.
7. **Reset Identitas** in `[pb2]`: the default window stays "Terpasang". In the app, "Kamar Ayah"
   turns offline within about 45 s.
8. In the app, remove "Kamar Ayah" (Perangkat → Hapus). "Kamar Ibu" stays, schedules intact.
9. Open up to 4 windows with **Tambah Pillbox Virtual**: the button then disables ("4/4").
   `python main.py --profile pb2` while `[pb2]` is open is refused.
