# Hosting Backend (FastAPI)

**Status:** konfigurasi siap, belum pernah di-deploy. Dibuat 24 Nov 2026 untuk B4 di `docs/PROJECT_STATUS.md`.

## Syarat yang menentukan pilihan host

| Syarat | Alasan |
|---|---|
| **Satu proses yang terus hidup**, satu instance, satu worker | Socket perangkat (`/ws/device/...`), socket aplikasi (`/ws/app`) dan ack perintah disimpan di memori proses (`Backend/CLAUDE.md`). Serverless (Vercel, Lambda) tidak bisa |
| WebSocket masuk | Perintah ke pillbox dan push ke aplikasi |
| Tugas latar terus berjalan | Rules engine (dosis terlewat) dan presence (pillbox offline) |
| Koneksi ke Supabase | Pakai **session pooler (port 5432)** atau koneksi langsung: satu server, prepared statement jalan (`Backend/README.md`) |

## Pilihan yang disiapkan

| | Render (disarankan untuk demo) | Railway |
|---|---|---|
| File di repo | `render.yaml` (root) + `Backend/Dockerfile` | `Backend/Dockerfile` saja |
| Paket gratis | Ada. **Tidur setelah 15 menit tanpa trafik masuk**, bangun sekitar 1 menit. Heartbeat pillbox yang menyala (tiap 15 detik) membuatnya tetap bangun | Kredit uji coba, lalu berbayar |
| Migrasi otomatis sebelum deploy | Hanya paket berbayar (`preDeployCommand`) | Ada (*pre-deploy command* di dashboard) |
| Region dekat | `singapore` | Pilih Asia Tenggara di dashboard |

`railway.json` sengaja tidak dibuat: dokumentasi Railway (dibaca 24 Nov 2026) menyatakan *config as code* sudah deprecated dan berhenti untuk layanan lama pada 1 Des 2026. Railway otomatis membangun `Dockerfile` di folder layanan.

## Langkah: Render

1. Render Dashboard, **New**, **Blueprint**, pilih repo ini. Render membaca `render.yaml`.
2. Isi variabel rahasia saat diminta (sekali saja, tidak tersimpan di repo):
   - `DATABASE_URL`: URI Supabase **session pooler** (port 5432).
   - `JWT_ACCESS_SECRET`: **sama persis** dengan nilai di Vercel (server auth). Untuk produksi pakai nilai acak minimal 32 karakter, lalu ganti di kedua tempat.
   - `PROVISIONING_TOKEN`: token pabrik untuk emulator. Kosongkan untuk mematikan `/admin/devices`.
   - `EXPO_ACCESS_TOKEN`: kosongkan kecuali *enhanced push security* aktif di Expo.
3. Jalankan migrasi sekali dari laptop (paket gratis tidak punya pre-deploy): di `Backend/`, `uv run python -m scripts.migrate` dengan `DATABASE_URL` yang sama. Migrasi Prisma lebih dulu (`Mobile/`: `pnpm exec prisma migrate deploy`).
4. Setelah deploy, buka `https://<nama>.onrender.com/health` dan `/health/db`.
5. Hubungkan aplikasi dan emulator:
   - Vercel: `EXPO_PUBLIC_PILLBOX_API_URL=https://<nama>.onrender.com`, lalu redeploy (nilai `EXPO_PUBLIC_*` masuk saat build).
   - Emulator: `PILLCARE_BACKEND_URL=https://<nama>.onrender.com`.
   - `CORS_ORIGINS` di `render.yaml` sudah memuat `https://mpc-mobile.vercel.app`; tambahkan origin lain bila perlu.

## Langkah: Railway

1. **New Project**, **Deploy from GitHub repo**, lalu di pengaturan layanan set **Root Directory** = `Backend`. Railway memakai `Backend/Dockerfile`.
2. **Variables**: isi variabel yang sama seperti Render (lihat `Backend/.env.example`), termasuk `CORS_ORIGINS` dan `AUTH_MODE=app_jwt`.
3. **Settings**: *Pre-deploy command* `/app/.venv/bin/python -m scripts.migrate`, *Healthcheck path* `/health`, *Replicas* 1.
4. **Networking**: *Generate Domain*, lalu isi URL itu di Vercel dan emulator seperti langkah Render nomor 5.

## Yang belum diverifikasi

- Image Docker belum pernah dibangun: komputer ini tidak punya Docker. Bangun sekali dengan `docker build -t pillcare-backend Backend` sebelum deploy pertama.
- Port: `Dockerfile` memakai `$PORT` dari host (Render 10000) dan 8000 bila tidak ada. Untuk Railway, pastikan domain diarahkan ke port yang sama dengan `PORT`.
- Uji beban pernah menunjukkan satu proses mulai lambat sekitar 100 perangkat (audit 3 Nov, B5). Cukup untuk demo kelas.
