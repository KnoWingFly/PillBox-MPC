# PillCare: Status Project, Phase, dan To-Do

**Per 24 Nov 2026.** Dasar analisis: `origin/main` di commit **`f5a85cd`** (17 Nov 2026), ditambah semua branch remote. Dokumen ini menggantikan laporan verifikasi lama 17 Okt.

**Metode.** Membaca riwayat git, diff, dan kode di `main`. Test emulator dijalankan (hasil di bagian 7). Test backend **tidak** dijalankan karena butuh database uji terpisah (`TEST_DATABASE_URL`). Aplikasi, deployment Vercel, dan build EAS tidak dijalankan.

**Legenda:** ✅ selesai · 🟡 sebagian / perlu keputusan · ❌ belum · 🐞 bug terverifikasi

## Isi

1. [Ringkasan](#1-ringkasan)
2. [Posisi branch dan git](#2-posisi-branch-dan-git)
3. [Riwayat perubahan](#3-riwayat-perubahan)
4. [Status per komponen](#4-status-per-komponen)
5. [Phase project](#5-phase-project)
6. [Bug dan risiko terbuka](#6-bug-dan-risiko-terbuka)
7. [To-Do](#7-to-do)
8. [Verifikasi yang dilakukan](#8-verifikasi-yang-dilakukan)
9. [Peta dokumen](#9-peta-dokumen)

---

## 1. Ringkasan

1. **Semua pekerjaan sudah terkumpul di `main`.** Tiga pull request (#1 integrasi backend, #2 onboarding dan auth mobile, #3 *robustness hardening*) sudah di-merge pada 23 Okt dan 5 Nov. Setelah itu ada 11 commit langsung ke `main` (6–17 Nov).
2. **Perubahan terbaru (6–17 Nov) ada di Mobile:**
   - login Google di web memakai alur redirect OAuth Supabase (`/auth/google-callback`);
   - perbaikan register email ganda;
   - deployment web dan server auth ke **Vercel**;
   - konfigurasi build **EAS**.
   Backend dan SmartDevice **tidak berubah** sejak 4 Nov (`f40b196`).
3. **Fungsi inti sudah lengkap.** Provisioning, pairing dengan PIN, jadwal 8 slot, sinkron jadwal lewat WebSocket, penilaian dosis (TAKEN/MISSED), notifikasi realtime, offline-first di emulator, role per lansia, dan rate limit autentikasi semuanya ada di kode.
4. **Yang belum:**
   - push notification ke HP (masih stub);
   - hosting backend (belum diputuskan);
   - halaman jadwal untuk profil lansia baru (masih placeholder);
   - beberapa permintaan backend dari tim mobile (`Mobile/BACKEND_HANDOFF.md` item 5, 6, 7, 9).
5. **Satu bug lama masih ada:** `PUT /devices/{id}/schedules/{schedule_id}` masih menyimpan jam sebagai string (🐞 B1). Perbaikannya sudah ada di branch `hezki` (`a3bac7f`) sejak 5 Okt, tetapi belum pernah di-merge. Aplikasi tidak memakai endpoint ini (ia memakai simpan batch), tetapi Postman dan klien lain memakainya.

---

## 2. Posisi branch dan git

| Branch | Commit teratas | Status terhadap `main` |
|---|---|---|
| `main` (remote) | `f5a85cd` (17 Nov) | Cabang utama, berisi semua pekerjaan |
| `hezki` | `ed561bb` (6 Nov) | 8 commit di luar `main`, tetapi isinya hanya **1 baris**: perbaikan `PUT` jadwal (`a3bac7f`). Sisanya commit merge |
| `backend/connect-pillbox`, `feat/*`, `fix/*`, `frontend/connect-pillbox` | lama | Sudah ter-merge ke `main`. Aman untuk dihapus di GitHub bila tim setuju |

**Kondisi repo lokal (komputer ini):**
- `main` lokal **2 commit di depan** `origin/main`, belum di-push:
  - `7144b33` menambah `docs/WEBSOCKET_DEEP_DIVE.md`;
  - `8d595aa` adalah commit merge dari `git pull`.
- Ada 2 stash GitHub Desktop (10 Nov). `stash@{1}` berisi catatan tugas mata kuliah (laporan auth, panduan UTS, diagram). Isinya sudah dikembalikan ke `docs/notes/` (lokal saja, tidak ikut git). Stash tidak dihapus.

---

## 3. Riwayat perubahan

| Tanggal | Isi | Commit / PR |
|---|---|---|
| 28–30 Sep | Monorepo awal; emulator PySide6 dengan SQLite, scheduler 8 slot, digital twin 3 zona, refill mode | `622c3c8` … `e6d1a0e` |
| 5–17 Okt | Backend inti: model dan migrasi, protokol perangkat (heartbeat, config, config-ack, telemetry), rules engine, adherence, auth server dan app terhubung ke backend nyata. WebSocket `/ws/device` dan `/ws/app`, sinkron emulator yang dipicu event | `1c09597` … `341e9bd` |
| 17–18 Okt | Konteks devices di app, swipe-to-delete, ikon speaker, dokumentasi Postman | `53b6e73` … `3dde8f6` |
| 23 Okt | Pooler transaksi Supabase, pool kecil, `503` saat database sibuk, *advisory lock* untuk tugas latar. Panduan agent (`CLAUDE.md`, `.claude/`, `.agents/`, `docs/ai/`) | `607aa0a`, `f2e8664`, `d98ca74`; **PR #1** |
| 24 Okt – 3 Nov | Validasi profil lansia; Expo SDK 58; protokol perangkat diperkuat; tombol hentikan alarm; outbox emulator lebih tahan error; layar onboarding, masuk, dan buat akun; panggilan jurnal, jam, dan preferensi notifikasi; redesain tab; laporan audit backend dan IoT | `6dc2845` … `4d84a0c`; **PR #2** |
| 4 Nov | *Robustness hardening*: penghitung percobaan PIN di database (migrasi 0007), indeks log event (0008), default `notify_on_taken` TRUE (0009); rate limit route auth; rotasi refresh token atomik; penerapan config di emulator atomik; beban polling app dikurangi | `aa5037f` … `9df4bd6`; **PR #3** (merge 5 Nov) |
| 6 Nov | Login Google di web lewat redirect OAuth (PKCE); perbaikan deteksi email ganda di Prisma; folder Postman *Access control demo* | `445382b`, `79d047c`, `41052cd` |
| 16–17 Nov | Deployment Vercel (Expo server output dan adapter `api/index.js`); `binaryTargets` Prisma untuk Linux; skrip salin query engine; konfigurasi EAS | `e4f8645` … `f5a85cd` |

### Detail perubahan terbaru (6–17 Nov)

| Area | Perubahan | File |
|---|---|---|
| Login Google (web) | Web tidak lagi memakai SDK native. Aplikasi memanggil `supabase.auth.signInWithOAuth` dengan `redirectTo` ke `/auth/google-callback`. Layar callback menukar `code` menjadi sesi Supabase (`exchangeCodeForSession`, alur PKCE), lalu menukarnya ke token PillCare lewat `POST /api/auth/google`. Sesi Supabase di web disimpan sementara di `sessionStorage`, lalu di-sign-out | `Mobile/context/auth-context.tsx`, `Mobile/src/app/auth/google-callback.tsx`, `Mobile/utils/supabase.ts` |
| Login Google (native) | Pesan error lebih jelas: tahap mana yang gagal (`googleSignInStage`) dan alasan tombol tidak tersedia (web client ID kosong, modul native tidak ada di Expo Go) | `Mobile/src/lib/google-signin.ts` |
| Register email ganda | Sebelumnya bisa menghasilkan 500 karena `instanceof Prisma...` gagal di bundel server. Kini dicek dari kode error `P2002` | `Mobile/src/server/users.ts` |
| Deployment web | `vercel.json`: build `prisma generate`, lalu `expo export --platform web`, lalu salin query engine Prisma. Semua request diarahkan ke satu fungsi `api/index.js` (`expo-server/adapter/vercel`). URL yang disebut di README: `https://mpc-mobile.vercel.app` | `Mobile/vercel.json`, `Mobile/api/index.js`, `Mobile/scripts/copy-prisma-engine.js`, `Mobile/prisma/schema.prisma` |
| Build EAS | Profil `development`, `preview` (APK), `production`; `projectId` EAS di `app.json` (juga dipakai untuk token push Expo) | `Mobile/eas.json`, `Mobile/app.json` |
| Postman | Folder *Access control demo*: login sebagai caregiver lain, lalu mencoba mengubah jadwal milik caregiver pertama (`404`) | `docs/postman/*` |

---

## 4. Status per komponen

### 4.1 Backend (FastAPI)

| Aspek | Status |
|---|---|
| Endpoint | ✅ **65 operasi HTTP** (24 Nov: +6 Roles, +2 mute per pillbox, +1 factory reset, −1 undangan email) + 2 WebSocket (`/ws/device/{code}`, `/ws/app`) |
| Protokol perangkat | ✅ Heartbeat, config bernomor versi (`304` bila tidak berubah), config-ack, telemetry idempoten per `event_id`, penolakan per event |
| Perintah ke perangkat | ✅ `trigger_alarm`, `stop_alarm`, `schedule_updated`, `time_sync`, `refill_mode`, `release_slot`, dengan ack ≤ 10 detik |
| Tugas latar | ✅ Rules engine (30 detik) dan presence (5 detik), pool koneksi terpisah, *advisory lock* agar hanya satu instance yang menjalankan |
| Keamanan | ✅ JWT HS256, device key SHA-256, PIN scrypt, batas percobaan PIN per perangkat di database, 404 vs 403, `lock_timeout` |
| Push notification ke HP | ✅ Expo Push API setelah commit (`services/push.py`), judul per bahasa, prioritas tinggi untuk peringatan, receipt dibaca 15 menit kemudian. Diuji dengan server Expo tiruan; belum dicoba ke HP sungguhan |
| WhatsApp | ❌ Hanya kolom `whatsapp_enabled`/`whatsapp_number` di model lansia, tanpa pengiriman |
| Hosting | 🟡 Konfigurasi siap (Render: `render.yaml` + `Backend/Dockerfile`; Railway: Dockerfile), belum di-deploy. Langkah: `docs/DEPLOY_BACKEND.md` |
| Roles (24 Nov, belum di-commit) | 🟡 Ubah akses, undangan berkode sekali pakai, batas anggota dan batas undangan, ADMIN hanya memberi PEMANTAU, push `roles` lewat `/ws/app`. Migrasi `0010`–`0011` sudah diterapkan ke database bersama (24 Nov). Uji alur lewat API: 54/54 cek lulus setelah perbaikan review kode. Rincian `docs/ROLES_FEATURE_PLAN.md` |
| Test | 110 fungsi test di `Backend/tests/` (12 baru di `test_caregivers.py`); tidak dijalankan untuk dokumen ini |

### 4.2 Server auth (Expo API routes)

| Aspek | Status |
|---|---|
| Endpoint | ✅ 14 operasi: register, login, Google, refresh, logout, lupa/reset/ganti password, setting, push token |
| Keamanan | ✅ bcrypt, rotasi refresh token atomik dengan grace 10 detik, rate limit login/register/forgot/reset di tabel `auth_attempts`, akun OWNER tidak bisa dihapus (`409 CANNOT_REMOVE_OWNER`) |
| Hosting | ✅ Konfigurasi Vercel ada (tidak diverifikasi berjalan). Lokal tetap di dev server Expo `:8081` |
| Yang diminta tim mobile | ❌ Batas sesi absolut 30 hari di server, refresh token pendek untuk "Ingat saya" mati, refresh token di cookie `HttpOnly` untuk web, pembersihan push token saat sesi berakhir (`BACKEND_HANDOFF.md` item 9) |

### 4.3 Aplikasi caregiver (Expo SDK 58)

| Aspek | Status |
|---|---|
| Layar | ✅ Onboarding, masuk, buat akun, lupa dan reset password, callback Google, dashboard 5 tab (beranda, jadwal, notifikasi, perangkat, pengaturan), tambah profil lansia |
| Realtime | ✅ Satu klien `/ws/app`; polling cadangan melambat menjadi 60 detik saat socket hidup |
| Pairing | ✅ Pindai QR atau ketik kode, buat PIN (pillbox baru) atau gabung dengan PIN (pillbox yang sudah dipakai) |
| Jadwal | ✅ Simpan batch `PUT /devices/{id}/schedules` |
| Halaman jadwal lansia baru | 🟡 `src/app/elderly/[id]/schedule.tsx` masih placeholder ("segera hadir") |
| Anggota keluarga (24 Nov, belum di-commit) | 🟡 Layar Anggota (`elderly/[id]/members.tsx`): daftar, ubah akses, keluarkan, alih kepemilikan, keluar, undang lewat kode (WhatsApp/bagikan), batalkan undangan. Gabung lewat kode dari Pengaturan dan layar Hubungkan Pillbox. Lint dan `tsc` lulus; belum dicoba di aplikasi |
| Sisa template | 🟡 `src/app/explore.tsx` (layar contoh Expo) masih terdaftar di `_layout.tsx` |
| Mode mock | ℹ️ Tanpa `EXPO_PUBLIC_PILLBOX_API_URL`, dashboard memakai data tiruan. Ini juga berlaku untuk web di Vercel sampai backend di-hosting |
| iOS | 🟡 `iosUrlScheme` di `app.json` masih placeholder |
| Test | Belum ada test runner. Lint punya 2 error lama yang diketahui (`Mobile/CLAUDE.md`) |

### 4.4 SmartDevice (emulator)

| Aspek | Status |
|---|---|
| Fungsi | ✅ Digital twin 8 slot, RTC simulasi (1x/10x/60x), offline-first dengan outbox SQLite, refill mode, multi-profil (`--profile pb2`), QR pairing |
| Komunikasi | ✅ REST (heartbeat, telemetry, config) dan klien WebSocket dengan backoff ber-jitter dan penanganan kode close `4401`/`4000`/`1011` |
| Bug lama dari Okt | ✅ Semua tertutup: `ALARM_STARTED`/`ALARM_STOPPED` sudah ada di `CHECK` SQLite, koneksi SQLite memakai lock, status pintu dikirim `OPEN`/`CLOSED` sesuai keadaan, perintah dengan `command_id` yang sama tidak dijalankan dua kali |
| Sisa kecil | 🟡 `applied_at` di config-ack jatuh ke jam lokal tanpa zona bila jam perangkat tidak tersedia (`core/sync.py`, sekitar baris 490) |

### 4.5 Database (Supabase Postgres)

- ✅ **19 tabel**: 13 dari migrasi SQL backend (`0001`–`0011` diterapkan) dan 6 dari Prisma (termasuk `auth_attempts`). Kepemilikan per tabel: `docs/ai/architecture.md`.
- ✅ RLS aktif di semua tabel tanpa policy, sehingga hanya server yang bisa membaca.
- 🟡 Indeks `notifications_event_key_idx` redundan (audit L6). Menghapusnya butuh persetujuan karena destruktif.
- ✅ `0010` (scope `CAREGIVER_INVITE`) dan `0011` (kolom `code_hash`, `expires_at` di `invitations`) diterapkan ke database bersama pada 24 Nov 2026.
- Migrasi berikutnya bernomor `0012`.

### 4.6 Dokumentasi dan tooling

- ✅ Panduan agent bersama: `CLAUDE.md` per folder, `.claude/` (rules, 3 agent reviewer, 5 command), `.agents/` (Antigravity), `docs/ai/`.
- 🟡 API list (spreadsheet) belum mencatat: parameter `device_id` di `GET`/`DELETE /notifications`, pagination `GET /devices` dan `GET /elderly/{id}/caregivers` (sudah ada di kode), dan `DELETE /devices/{id}/alarm`.
- 🟡 Koleksi Postman: 72 request, tetapi `DELETE /devices/{id}/alarm` belum masuk (`docs/postman/README.md`).

---

## 5. Phase project

| Phase | Isi | Status |
|---|---|---|
| **0. Fondasi** | Monorepo, kontrak API dan ERD, emulator dasar | ✅ Selesai (Sep) |
| **1. Backend inti dan protokol perangkat** | Model dan migrasi, protokol REST perangkat, rules engine, adherence, role | ✅ Selesai (awal Okt) |
| **2. Integrasi dan realtime** | App terhubung ke backend nyata, WebSocket `/ws/device` dan `/ws/app`, sinkron emulator berbasis event | ✅ Selesai (17 Okt) |
| **3. UTS** | Presentasi tengah semester, Postman, slide | ✅ Selesai (Okt) |
| **4. Hardening dan audit** | Audit reliabilitas, perbaikan C1–M16, rate limit, penghitung di database, perbaikan emulator | ✅ Hampir selesai. Sisa: H9 (keputusan hosting), L6 (indeks redundan), M8 (retensi notifikasi) |
| **5. Auth dan Grand Bonus (Modul 8)** | Login Google web, laporan auth, video demo | 🟡 Kode selesai (6 Nov). Laporan dan video: status pengumpulan tidak tercatat di repo |
| **6. Deployment** | Web dan auth di Vercel, build mobile EAS, hosting backend | 🟡 Berjalan: konfigurasi Vercel dan EAS ada; **hosting backend belum ada**, sehingga web yang di-hosting masih memakai data tiruan |
| **7. Fitur lanjutan** | Push notification ke HP, halaman jadwal lansia, item handoff 5–9 (24 Nov); WhatsApp belum | 🟡 Sebagian besar selesai |

---

## 6. Bug dan risiko terbuka

| # | Masalah | Dampak | Bukti | Perbaikan |
|---|---|---|---|---|
| ✅ B1 | `PUT /devices/{id}/schedules/{schedule_id}` gagal 500 (jam disimpan sebagai string) | — | — | **Diperbaiki 24 Nov**: cherry-pick `a3bac7f` + test `test_single_schedule_update_*`; diuji end-to-end |
| ✅ B2 | Error umum (500, 503, 409 race) tanpa header CORS | — | — | **Diperbaiki 24 Nov**: `UnhandledErrorMiddleware` di dalam CORS (`app/core/errors.py`) + test; diuji pada app nyata |
| ✅ B3 | Push notification ke HP belum ada | — | — | **Diperbaiki 24 Nov**: `services/push.py` + `tests/test_push.py`; diuji dengan server Expo tiruan |
| 🟡 B4 | Backend belum di-hosting | Web di Vercel hanya menampilkan data tiruan | — | Konfigurasi Render/Railway siap (`docs/DEPLOY_BACKEND.md`), tim tinggal membuat akun dan deploy |
| ⚠️ B5 | Skalabilitas satu proses | p95 di atas 500 ms setelah sekitar 100 perangkat; satu worker mendekati 100% CPU di sekitar 2.500 socket app (hasil uji beban audit) | `docs/audits/backend-iot-audit-2026-11-03.md` §9 | Butuh keputusan hosting; lebih dari satu worker berarti memindahkan state socket ke luar proses |
| ℹ️ B6 | `Mobile/src/app/explore.tsx` sisa template Expo masih bisa dibuka | Tidak berbahaya, tetapi membingungkan | `_layout.tsx` baris 60 | Hapus route dan file bila tidak dipakai |
| ℹ️ B7 | Koleksi Postman belum punya `DELETE /devices/{id}/alarm` | Endpoint hentikan alarm tidak bisa didemokan lewat koleksi | Perbandingan route vs koleksi | Tambahkan ke folder *Devices* |

---

## 7. To-Do

### P0: sebelum demo atau pengumpulan berikutnya

- [ ] Push branch `feat/roles-invitations` dan buat PR (semua pekerjaan 24 Nov ada di sana).
- [ ] Jalankan test backend dengan database uji (`uv run pytest`, `TEST_DATABASE_URL` ke Postgres lokal): 117 test terkumpul, belum pernah dijalankan di mesin ini.
- [ ] Laporan Grand Bonus: isi `[ISI LINK YOUTUBE DI SINI]` di `docs/notes/AUTH_GRAND_BONUS_REPORT.md` dan `AUTH_REPORT_FINAL.md` (lokal), lalu kumpulkan.
- [ ] Tempel DBML di `docs/ROLES_FEATURE_PLAN.md` ("Perubahan ERD") ke dbdiagram.io (butuh akun pemilik diagram).
- [ ] Kabari tim: database bersama sudah sampai `0012` + Prisma `20261124000000`, API list memuat endpoint baru, undangan email dihapus.
- [ ] Aplikasi tetap bisa dipakai saat pillbox mati (beranda dan menu lain tetap terbuka).
- [ ] Peringatan "Hydration failed" di web: ikon Ionicons dirender berbeda di server dan browser (font dimuat hanya di browser, `src/app/_layout.tsx`).

### P1: kelengkapan fitur

- [x] Push notification lewat Expo Push API (B3).
- [x] Halaman jadwal untuk profil lansia (`Mobile/src/app/elderly/[id]/schedule.tsx`).
- [x] Item `Mobile/BACKEND_HANDOFF.md` 5, 6 (mute per pillbox), 7 (factory reset), 9 (sesi absolut, "Ingat saya" pendek, cookie `HttpOnly` di web, pembersihan push token).
- [x] Header CORS pada respons error umum (B2).
- [x] Endpoint undangan email lama dihapus (`POST /elderly/{id}/caregivers`).
- [x] Konfigurasi hosting Backend (Render/Railway).
- [ ] Deploy Backend dan isi `EXPO_PUBLIC_PILLBOX_API_URL` di Vercel (`docs/DEPLOY_BACKEND.md`).
- [ ] Coba push di HP sungguhan (development build, bukan Expo Go).
- [ ] WhatsApp: hanya kolom di database, belum ada pengiriman.
- [ ] Isi `iosUrlScheme` di `app.json` bila build iOS dibutuhkan.

### P2: dokumentasi dan kerapian

- [x] API list diperbarui untuk pekerjaan 24 Nov: Roles (sheet *Profil_Lansia*, *Realtime*), `PUT`/`DELETE /devices/{id}/membership`, `is_muted`, `?purge_my_notifications`, `POST /admin/devices/{code}/reset` (*PerangkatPillbox*), `remember` dan cookie di login/Google/refresh/logout (*Auth&Account*); baris undangan email ditandai DIHAPUS.
- [ ] API list masih belum memuat: `device_id` di `GET`/`DELETE /notifications`, pagination `GET /devices` dan daftar caregiver, `DELETE /devices/{id}/alarm`. Baris Google login masih menyebut `google_id_token`, padahal kode memakai `supabase_access_token`; respons register di sheet juga tidak memuat token.
- [ ] Tambahkan `DELETE /devices/{id}/alarm`, 6 request Roles, 2 mute dan 1 reset ke koleksi Postman (B7).
- [ ] Hapus `explore.tsx` (B6) bila tim setuju.
- [ ] Putuskan penghapusan indeks redundan `notifications_event_key_idx` (audit L6, butuh persetujuan).
- [ ] Hapus branch lama yang sudah ter-merge di GitHub (`backend/connect-pillbox`, `feat/*`, `fix/*`, `frontend/connect-pillbox`) dan branch `hezki` (B1 sudah masuk lewat cherry-pick).
- [ ] `applied_at` config-ack memakai waktu ber-zona (SmartDevice, sisa D7).

### Selesai sejak laporan 17 Okt

- [x] WebSocket emulator, perintah alarm per slot (`ALARM_STARTED` di `CHECK`), lock SQLite, status pintu nyata.
- [x] Register email ganda tidak lagi 500 (`41052cd`).
- [x] Default `notify_on_taken` TRUE (migrasi `0009`).
- [x] Rate limit auth, penghitung PIN per perangkat di database, rotasi token atomik.
- [x] `/ws/app` ditutup saat token kedaluwarsa dan berhenti mengirim ke caregiver yang dikeluarkan.
- [x] `/pairing/scan` tidak membocorkan nama lansia ke orang asing dan dibatasi per user.
- [x] Pagination `GET /devices` dan daftar caregiver (kode).
- [x] Login Google di web, deployment Vercel, konfigurasi EAS.
- [x] Penghapusan akun OWNER ditolak `409 CANNOT_REMOVE_OWNER`.

---

## 8. Verifikasi yang dilakukan

| Yang dicek | Cara | Hasil |
|---|---|---|
| Isi branch dan commit | `git fetch`, `git log`, diff antar branch | Lihat bagian 2–3 |
| Bug B1 | Menjalankan `ScheduleUpdateIn(...).model_dump(exclude_unset=True)` dengan venv backend | Jam keluar sebagai `str`: bug masih ada |
| Bug emulator lama | Membaca `schema.sql`, `db/database.py`, `core/sync.py` | Tertutup |
| Test emulator | `QT_QPA_PLATFORM=offscreen pytest` dengan `Backend/.venv` | **104 lulus, 3 gagal** di `test_sync.py`; 2 modul (`test_alarm_commands.py`, `test_main_window.py`) tidak terkumpul. Semua kegagalan karena paket `segno` tidak terpasang di venv itu, bukan karena kode. Jalankan ulang dengan venv SmartDevice sendiri (`pip install -r requirements.txt`) |
| Endpoint vs Postman | Mencocokkan dekorator route backend dengan koleksi | 56 dari 57 operasi backend dan 14 dari 14 operasi auth ada di koleksi |
| Jumlah tabel | Migrasi SQL dan model Prisma | 13 + 6 = 19 |
| Test backend | Tidak dijalankan | — |
| Aplikasi, Vercel, EAS | Tidak dijalankan | — |

---

## 9. Peta dokumen

| Dokumen | Isi | Status |
|---|---|---|
| `docs/PROJECT_STATUS.md` | Status, phase, to-do (dokumen ini) | Terkini |
| `CLAUDE.md`, `*/CLAUDE.md`, `docs/ai/*` | Aturan kerja, domain, arsitektur, kepemilikan tabel | Terkini (keputusan hosting auth dan hapus akun OWNER diperbarui 24 Nov) |
| `docs/DEVICE_CONTRACT.md` | Kontrak pesan perangkat dan backend | Terkini (4 Nov) |
| `docs/WEBSOCKET_DEEP_DIVE.md` | Penjelasan WebSocket langkah demi langkah dengan nomor baris | Terkini; nomor baris berlaku untuk `main` per 24 Nov |
| `docs/ROLES_FEATURE_PLAN.md` | Rancangan fitur Roles: anggota keluarga, ubah akses, undangan berkode, UI layar Anggota | Diimplementasi 24 Nov (belum di-commit, test belum dijalankan) |
| `docs/audits/system-audit-2026-11-24.md` | Audit sistem menyeluruh (keamanan, role, IoT, mobile, privasi, operasional) dengan prioritas perbaikan | Terkini (24 Nov) |
| `docs/audits/backend-iot-audit-2026-11-03.md` | Audit reliabilitas dan status perbaikannya (§9) | Rekaman per 3–4 Nov |
| `docs/postman/README.md` | Cara memakai koleksi Postman | Terkini (angka diperbarui 24 Nov) |
| `Backend/README.md`, `SmartDevice/README.md`, `Mobile/README.md` | Cara menjalankan tiap bagian | Terkini (`Mobile/README.md` dirapikan 24 Nov) |
| `Mobile/BACKEND_HANDOFF.md` | Permintaan backend dari tim mobile | Terkini: item 1–4 selesai, 5–9 terbuka |
| `docs/PERFORMANCE_FINDINGS_EMULATOR.md` | Audit delay emulator 17 Okt | Historis; status D1–D7 ditambahkan di atas |
| `docs/HANDOVER_SYSTEM_ARCHITECTURE.md` | Serah-terima awal (30 Sep) | Historis; dipertahankan karena dirujuk migrasi `0001` |
| `docs/SMART_DEVICE_SPEC_AND_FEATURES.md` | Spesifikasi awal emulator (30 Sep) | Historis |
| `AUTH_REPORT_NOTES.md` (root) | Catatan bahan laporan auth (berbasis `d777e44`) | **Dikeluarkan dari git** (24 Nov); salinan lokal di `docs/notes/` |
| `docs/notes/` | Catatan tugas mata kuliah (laporan auth, panduan demo, panduan UTS, diagram) | Lokal saja, dikecualikan lewat `.git/info/exclude` |
| `Mobile/.claude/`, `.agents/`, `.cursor/`, `.devin/` | Skill Prisma yang disinkronkan `pnpm install` | Dibiarkan (sesuai `docs/ai/README.md`) |
