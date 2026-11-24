# Audit Sistem PillCare — 24 Nov 2026

Audit menyeluruh terhadap keamanan, otorisasi, perangkat IoT, aplikasi mobile, privasi, kebenaran fungsi, performa, dan operasional. Audit sebelumnya (`backend-iot-audit-2026-11-03.md`) berfokus pada reliabilitas backend dan IoT; temuannya yang sudah diperbaiki tidak diulang di sini.

## 1. Ruang lingkup dan metode

**Objek:** `origin/main` commit `f5a85cd` (17 Nov 2026): `Backend/`, `Mobile/` (aplikasi dan server auth), `SmartDevice/`, konfigurasi deployment (`Mobile/vercel.json`, `Mobile/eas.json`), dan dokumentasi.

**Acuan:**

| Acuan | Dipakai untuk |
|---|---|
| OWASP ASVS 5.0 (Mei 2025), target Level 2 | Server: autentikasi, sesi, otorisasi, validasi, konfigurasi |
| OWASP API Security Top 10 2023 | Kerentanan khas API (BOLA, autentikasi, konsumsi sumber daya, inventaris) |
| OWASP MASVS v2.1 | Aplikasi mobile: penyimpanan, jaringan, privasi |
| OWASP IoT Top 10 2018 | Perangkat: kredensial, layanan jaringan, mekanisme update dan reset |
| UU No. 27/2022 (Pelindungan Data Pribadi) | Data kesehatan sebagai data pribadi spesifik |
| STRIDE | Menyusun skenario ancaman per jalur (app → auth server, app → backend, perangkat → backend) |

**Cara kerja:** membaca kode dan konfigurasi, menelusuri setiap jalur autentikasi dan otorisasi, mencocokkan endpoint dengan koleksi Postman, memindai riwayat git untuk secret, dan menjalankan pemeriksaan yang aman dilakukan lokal.

**Status bukti:** **V** = diverifikasi dengan menjalankan sesuatu · **R** = disimpulkan dari pembacaan kode, belum dijalankan.

**Skala keparahan:** **Tinggi** (mengganggu fungsi inti atau membuka akses yang tidak semestinya) · **Sedang** (celah nyata dengan prasyarat, atau fungsi penting belum ada) · **Rendah** (pengerasan atau kerapian) · **Info** (keterbatasan desain yang perlu disadari).

**Tidak dilakukan:** test backend (butuh database uji terpisah), menjalankan aplikasi atau build EAS, uji deployment Vercel, uji penetrasi aktif, dan pemindaian dependensi. `pnpm audit` gagal karena koneksi ke registry npm terputus. Typecheck `tsc` tidak bisa dijalankan karena `node_modules` Mobile tidak sinkron dengan lockfile (lihat O6).

---

## 2. Ringkasan

| Keparahan | Jumlah | Contoh |
|---|---|---|
| Tinggi | 4 | Bug simpan jadwal tunggal (C1); push notification belum ada (M1); backend belum di-hosting (O1); pengelolaan caregiver tidak ada di aplikasi (A1) |
| Sedang | 10 | Enumerasi email lewat undangan (S1); undangan tanpa persetujuan (S2); tidak ada verifikasi email (S3); token web rentan XSS tanpa header keamanan (S8); CORS hilang di respons error (C2); privasi data kesehatan (P1) |
| Rendah | 13 | Kepercayaan `X-Forwarded-For` (S4); token provisioning (S5); `/docs` terbuka (S7) |
| Info | 4 | "Dibuka ≠ diminum" (I1) |

**Kekuatan yang perlu dipertahankan:**
- Otorisasi ditegakkan terpusat di backend, dengan aturan 404 vs 403 yang konsisten dan test-nya ada.
- Password memakai bcrypt dan waktu respons login seragam. PIN memakai scrypt dengan batas percobaan per perangkat di database.
- Refresh token dirotasi secara atomik dan pemakaian ulangnya dideteksi.
- Device key disimpan sebagai hash dan dibandingkan *constant-time*.
- RLS aktif di semua tabel. Tidak ada secret di riwayat git. Tidak ada SQL yang dirakit dari string.
- OTP hanya dicetak ke console saat `NODE_ENV=development`.

---

## 3. Temuan: keamanan autentikasi

| ID | Keparahan | Temuan | Bukti | Status | Saran |
|---|---|---|---|---|---|
| S1 | Sedang | **Enumerasi email lewat undangan caregiver.** `POST /elderly/{id}/caregivers` menjawab `404 CAREGIVER_NOT_REGISTERED` bila email belum terdaftar, `409 ALREADY_CAREGIVER`, atau `201`. Siapa pun bisa membuat profil lansia (otomatis OWNER), lalu memakai endpoint ini untuk memeriksa email mana yang punya akun, tanpa batas percobaan. Ini meniadakan upaya anti-enumerasi di login dan lupa password (API Top 10: API2/API4) | `Backend/app/services/elderly.py` `invite()`; tidak ada `register_attempt` di file itu | R | Batasi percobaan undangan per user (pakai `attempt_counters`), atau ubah menjadi undangan bertoken yang jawabannya selalu sama |
| S2 | Sedang | **Undangan langsung menambahkan orang tanpa persetujuannya.** Baris `invitations` langsung berstatus `ACCEPTED`. Seseorang bisa dimasukkan ke profil lansia orang lain dan mulai menerima notifikasi kesehatan tanpa pernah setuju | `invite()`: komentar "ASSUMPTION" | R | Undangan `PENDING` + endpoint terima/tolak (tabel dan statusnya sudah ada) |
| S3 | Sedang | **Tidak ada verifikasi email saat registrasi.** Orang bisa mendaftar memakai email milik orang lain. Akibatnya: (a) undangan bisa masuk ke akun palsu; (b) pemilik email asli yang kemudian masuk dengan Google ditolak `409 EMAIL_ALREADY_REGISTERED` karena akun password sudah ada | `Mobile/src/app/api/auth/register+api.ts`; tidak ada alur verifikasi | R | Verifikasi email dengan OTP sebelum akun aktif atau sebelum bisa diundang |
| S4 | Rendah | **Rate limit per-IP memercayai `X-Forwarded-For` mentah.** `clientIp()` mengambil elemen pertama header itu, yang bisa diisi bebas oleh klien bila server tidak berada di belakang proxy yang menimpanya (dev server, LAN, host lain). Batas per-email tetap berlaku untuk login, forgot, dan reset, tetapi batas register per-IP bisa dilewati | `Mobile/src/server/http.ts` baris 85–89 | R. Perilaku di Vercel belum diverifikasi | Ambil IP dari header yang dijamin platform, atau jadikan proxy tepercaya sebagai konfigurasi |
| S5 | Rendah | **Token provisioning statis tanpa batas percobaan dan tanpa panjang minimum.** Pemegang token bisa merotasi secret perangkat mana pun berdasarkan `device_code`, yang membuat perangkat itu tidak bisa terhubung lagi. Emulator membaca token ini dari `Backend/.env`; wajar untuk emulator, tetapi perangkat asli tidak boleh menyimpan kredensial pabrik | `Backend/app/api/routes/admin.py`; `SmartDevice/smart_pillbox/config.py` baris 190–211 | R | Validasi panjang minimum, batas percobaan, catat audit setiap provisioning dan rotasi |
| S6 | Rendah | Backend tidak memvalidasi panjang `JWT_ACCESS_SECRET`. Server auth mewajibkan ≥ 32 karakter, sedangkan backend menerima nilai apa pun | `Backend/app/core/config.py` (tanpa validator); `Mobile/src/server/env.ts` baris 13 | R | Tambahkan validator yang sama di backend |
| S7 | Rendah | `/docs`, `/redoc`, dan `/openapi.json` aktif di semua lingkungan, sehingga seluruh permukaan API terbuka untuk dipetakan | `Backend/app/main.py` baris 49 (`FastAPI(...)` tanpa `docs_url`) | R | Matikan lewat setting di produksi |
| S8 | Sedang (web) | **Token web rentan dicuri lewat XSS.** Refresh token disimpan di `localStorage` saat "Ingat saya", dan `vercel.json` tidak memasang header keamanan apa pun (CSP, HSTS, `X-Frame-Options`, `X-Content-Type-Options`) | `Mobile/src/lib/api/token-store.ts`; `Mobile/vercel.json` | R | Refresh token di cookie `HttpOnly; Secure; SameSite=Strict` (`BACKEND_HANDOFF.md` item 9), plus header keamanan di `vercel.json` |
| S9 | Info | Access token yang sudah terbit tidak bisa dicabut sebelum 15 menit; cache user di backend menambah jeda hingga 30 detik | `Backend/app/api/deps.py` | R | Sudah didokumentasikan; terima, atau cek sesi untuk endpoint sensitif |
| S10 | Rendah | Provisioning menerima secret pilihan perangkat dengan panjang minimal 16 karakter, jauh lebih lemah dari secret 256 bit buatan server | `Backend/app/services/provisioning.py` `_secret()`; `DEVICE_SECRET_MIN_LENGTH=16` | R | Selalu buat di server, atau naikkan minimum ke 43 karakter (256 bit base64url) |
| S11 | Info | Satu secret HS256 dipegang dua server, tanpa klaim `iss`/`aud` | `Backend/app/core/security.py`, `Mobile/src/server/tokens.ts` | R | Kunci asimetris bila server bertambah |

---

## 4. Temuan: otorisasi dan role

| ID | Keparahan | Temuan | Bukti | Status | Saran |
|---|---|---|---|---|---|
| A1 | Tinggi (fungsi) | **Pengelolaan caregiver tidak ada di aplikasi.** Backend menyediakan daftar caregiver, undang, keluarkan, keluar sendiri, dan alih kepemilikan, tetapi aplikasi tidak memanggil satu pun. Satu-satunya cara bergabung dari aplikasi adalah lewat PIN, yang selalu memberi role PEMANTAU, sehingga role ADMIN tidak bisa diberikan dari aplikasi sama sekali | Pencarian `/caregivers` dan `transfer-ownership` di `Mobile/lib`, `src`, `components`, `context` tidak menemukan apa pun | V (pencarian kode) | Layar "Anggota keluarga" di tab Pengaturan: daftar, undang (pilih ADMIN/PEMANTAU), keluarkan, keluar, alih kepemilikan |
| A2 | Rendah | **Tidak ada endpoint untuk mengubah role.** Menaikkan PEMANTAU menjadi ADMIN, atau sebaliknya, hanya bisa dengan mengeluarkan lalu mengundang ulang. ADMIN bisa mengundang ADMIN lain, tetapi tidak bisa mengeluarkan siapa pun; hanya OWNER yang bisa | `elderly.py` `remove_caregiver()`; daftar route di `routes/elderly.py` | R | `PUT /elderly/{id}/caregivers/{cid}` khusus OWNER (butuh perubahan API list); putuskan apakah ADMIN boleh memberi role ADMIN |
| A3 | Rendah | Non-OWNER hanya bisa keluar dari seluruh profil lansia, tidak per pillbox | `Mobile/BACKEND_HANDOFF.md` item 6 | R | Keputusan model data |
| A4 | Rendah | Pairing pertama hanya butuh kode perangkat. Pencarian kode sudah dibatasi 30 per 5 menit per user, tetapi kode yang diketahui orang lain (misalnya dari foto kemasan) tetap bisa diklaim lebih dulu | `device_management.py` `pair()` | R | Rahasia pairing dari pabrik atau tombol fisik di perangkat |
| A5 | Info | Penegakan role di backend konsisten: semua route device dan lansia lewat `access.py`, dengan test untuk 403 PEMANTAU, 404 orang asing, dan caregiver yang dikeluarkan berhenti menerima push | `Backend/app/services/access.py`, `tests/test_roles_and_commands.py`, `tests/test_hardening.py`, `tests/test_app_push.py` | R (test tidak dijalankan) | Pertahankan |

---

## 5. Temuan: kebenaran fungsi dan API

| ID | Keparahan | Temuan | Bukti | Status | Saran |
|---|---|---|---|---|---|
| C1 | Tinggi | **`PUT /devices/{id}/schedules/{schedule_id}` menyimpan jam sebagai string.** `model_dump(exclude_unset=True)` menjalankan serializer `HHMM`, sehingga `"07:00"` (string) disimpan ke kolom `TIME`. Aplikasi tidak terdampak (memakai simpan batch), tetapi Postman dan klien lain terdampak | `Backend/app/services/schedules.py` baris 315; dijalankan: `ScheduleUpdateIn(window_start='07:00').model_dump(exclude_unset=True)` menghasilkan `str` | V | Cherry-pick `a3bac7f` (pola yang sama dengan baris 402–403) dan tambahkan test |
| C2 | Sedang | **Respons error umum tanpa header CORS.** Handler `Exception` (500, 503 saat database sibuk, 409 dari *unique violation*) dijalankan di `ServerErrorMiddleware` di luar `CORSMiddleware`. Di browser, error itu tampil sebagai "tidak bisa menjangkau server" | `Backend/app/main.py` baris 49–60, `app/core/errors.py` baris 130–155 | R | Tambahkan header CORS pada respons handler itu, atau tangkap error di middleware di dalam lapisan CORS |
| C3 | Rendah | Koleksi Postman belum memuat `DELETE /devices/{id}/alarm`. API list belum memuat parameter `device_id` di notifikasi, pagination `GET /devices` dan daftar caregiver, maupun endpoint hentikan alarm (API Top 10: API9 inventaris) | Perbandingan route dengan koleksi | V | Perbarui koleksi dan API list |
| C4 | Rendah | `applied_at` di config-ack jatuh ke jam lokal tanpa zona waktu | `SmartDevice/smart_pillbox/core/sync.py` sekitar baris 490 | R | Pakai waktu ber-zona dari RTC |
| C5 | Rendah | Halaman jadwal profil lansia baru masih placeholder; layar contoh Expo `explore.tsx` masih bisa dibuka | `Mobile/src/app/elderly/[id]/schedule.tsx`; `_layout.tsx` baris 60 | V | Selesaikan halaman, hapus `explore.tsx` |

---

## 6. Temuan: perangkat IoT

| ID | Keparahan | Temuan | Bukti | Status | Saran |
|---|---|---|---|---|---|
| I1 | Info | **"Dibuka ≠ diminum."** Dosis dinilai TAKEN dari sensor tutup terbuka. Sistem tidak bisa membuktikan obat benar-benar ditelan | `docs/ai/domain.md`; alur telemetry | R | Nyatakan sebagai keterbatasan; konfirmasi manual oleh caregiver sudah tersedia |
| I2 | Sedang | **Tidak ada factory reset di server.** "Reset Identitas" di emulator hanya menghapus identitas lokal, sementara baris perangkat di server tetap ter-pair (OWASP IoT I9: pengaturan bawaan tidak aman) | `Mobile/BACKEND_HANDOFF.md` item 7; `routes/admin.py` hanya punya 2 route | R | `POST /admin/devices/{code}/reset` |
| I3 | Info | Secret perangkat disimpan sebagai teks biasa di SQLite emulator | `SmartDevice/smart_pillbox/db/database.py` | R | Wajar untuk emulator; hardware asli perlu secure element |
| I4 | Info | Belum ada mekanisme update firmware maupun konfigurasi aman di luar jadwal (OWASP IoT I4) | — | R | Di luar lingkup emulator; catat untuk perangkat asli |

---

## 7. Temuan: aplikasi mobile

| ID | Keparahan | Temuan | Bukti | Status | Saran |
|---|---|---|---|---|---|
| M1 | Tinggi (produk) | **Push notification ke HP belum ada.** Notifikasi dosis terlewat hanya sampai saat aplikasi terbuka (WebSocket dan polling). Untuk aplikasi pemantau lansia, inilah fungsi yang paling dibutuhkan saat aplikasi tertutup | `Backend/app/services/notifications.py` `dispatch_push()` (stub) | R | Kirim lewat Expo Push API setelah commit; `projectId` EAS sudah ada |
| M2 | Sedang | **Build APK Android kemungkinan tidak bisa menjangkau backend HTTP.** Build rilis Android memblokir HTTP non-TLS secara bawaan, dan `app.json` tidak mengizinkannya. Build `preview` di `eas.json` adalah APK rilis, sehingga alamat backend `http://<IP LAN>:8000` kemungkinan gagal | `Mobile/app.json`, `Mobile/eas.json`; tidak ada `expo-build-properties` | R, belum dibuktikan dengan build | Backend lewat HTTPS, atau izinkan cleartext khusus untuk demo |
| M3 | Rendah | `iosUrlScheme` untuk Google Sign-In di iOS masih placeholder | `Mobile/app.json` | V | Isi sebelum build iOS |
| M4 | Rendah | Beberapa teks UI dan warna hex masih di dalam komponen, bukan di `strings.ts`/token (misalnya `device-tab.tsx` baris 234–238, `qr-scanner.tsx` baris 32) | Pencarian kode | V | Pindahkan saat file itu disentuh |
| M5 | Info | Tidak ada test runner untuk Mobile | `Mobile/CLAUDE.md` | V | Minimal test untuk `lib/` dan `src/server/` |

---

## 8. Temuan: privasi (UU PDP)

| ID | Keparahan | Temuan | Bukti | Status | Saran |
|---|---|---|---|---|---|
| P1 | Sedang | **Data kesehatan tanpa persetujuan, retensi, maupun penghapusan nyata.** Jadwal obat dan riwayat dosis adalah data kesehatan, yang menurut UU PDP termasuk data pribadi spesifik. Masalahnya: tidak ada pemberitahuan privasi atau persetujuan saat membuat profil lansia; data disimpan di Supabase region Sydney (transfer lintas negara); penghapusan lansia hanya *soft delete*; tidak ada pekerjaan yang menghapus atau menganonimkan data lama; tidak ada ekspor data | Pencarian `retention`, `purge`, `hard_delete` di `Backend/app` tidak menemukan apa pun | R | Pemberitahuan dan persetujuan di onboarding dan saat membuat profil lansia; kebijakan retensi untuk notifikasi dan telemetri; hapus permanen setelah masa tenggang |
| P2 | Rendah | Nomor WhatsApp disimpan, tetapi kanal WhatsApp belum diimplementasikan. Data dikumpulkan tanpa dipakai | `Backend/app/models/elderly.py` baris 45–46 | R | Sembunyikan isian itu sampai kanalnya ada |

---

## 9. Temuan: operasional, performa, dan kualitas

| ID | Keparahan | Temuan | Bukti | Status | Saran |
|---|---|---|---|---|---|
| O1 | Tinggi | **Backend belum di-hosting.** Web di Vercel memakai data tiruan selama `EXPO_PUBLIC_PILLBOX_API_URL` kosong. Backend wajib satu proses jangka panjang, sehingga tidak bisa dijalankan sebagai fungsi serverless | `Mobile/README.md`; tidak ada konfigurasi deploy di `Backend/` | R | Pilih host proses jangka panjang dengan HTTPS |
| O2 | Sedang | **Batas skala satu proses.** Hasil uji beban audit 3 Nov: p95 di atas 500 ms setelah sekitar 100 perangkat, CPU satu worker 90–97% di sekitar 2.500 socket aplikasi | `docs/audits/backend-iot-audit-2026-11-03.md` §9 | V (audit sebelumnya) | Cukup untuk demo; untuk skala nyata, pindahkan state socket ke luar proses |
| O3 | Sedang | **Tidak ada CI.** Tidak ada workflow yang menjalankan test backend (98 fungsi), test emulator (107 kasus), lint, atau typecheck saat push. Bug C1 lolos dari 5 Okt sampai sekarang karena tidak ada test untuk endpoint itu | Tidak ada `.github/` | V | Workflow GitHub Actions: Postgres service + `pytest`, SmartDevice `pytest` offscreen, `tsc` dan lint Mobile |
| O4 | Rendah | Test emulator: 104 lulus, 3 gagal, 2 modul tidak terkumpul, semuanya karena `segno` tidak terpasang di venv yang dipakai (bukan karena kode) | Dijalankan dengan `Backend/.venv` | V | Venv SmartDevice sendiri sesuai `SmartDevice/README.md` |
| O5 | Rendah | Retensi notifikasi belum ada, sehingga hitungan feed terus bertambah (audit M8) | `docs/audits/backend-iot-audit-2026-11-03.md` | R | Kebijakan retensi (lihat P1) |
| O6 | Rendah | **Lingkungan pengembangan tidak sinkron.** `node_modules` Mobile tidak cocok dengan `pnpm-lock.yaml` setelah lockfile berubah (16–17 Nov). Perintah `pnpm exec` mencoba menginstal ulang | Diamati saat audit: `.modules.yaml` tidak ada, `tsc` tidak tersedia | V | `pnpm install` setiap kali lockfile berubah |
| O7 | Rendah | Indeks redundan `notifications_event_key_idx` (audit L6) | `Backend/migrations/0002…sql` | R | Hapus dalam migrasi `0010` setelah disetujui |
| O8 | Info | Banyak branch remote yang sudah ter-merge masih ada; branch `hezki` berisi perbaikan C1 yang belum di-merge | `git branch -r` | V | Merge perbaikan, lalu hapus branch lama |

---

## 10. Prioritas perbaikan

> **Pembaruan 24 Nov 2026 (sore).** Urutan 2 dan 3 sudah diimplementasi di working tree (belum di-commit, test backend belum dijalankan; migrasi `0010`–`0011` sudah diterapkan ke database bersama): A1 dan A2 tertutup di kode; S1 dimitigasi (batas undangan per user, endpoint email ditandai *deprecated*, undangan berkode tidak memerlukan email sama sekali); S2 tertutup untuk undangan berkode (`PENDING` sampai diterima), sedangkan endpoint email lama tetap langsung menambahkan sampai dihapus. Rincian: `docs/ROLES_FEATURE_PLAN.md`, "Status implementasi".

| Urutan | Perbaikan | Menutup | Perkiraan ukuran |
|---|---|---|---|
| 1 | Cherry-pick `a3bac7f` + test untuk `PUT` jadwal tunggal | C1 | Kecil |
| 2 | Layar pengelolaan anggota keluarga di Pengaturan (daftar, undang, keluarkan, keluar, alih kepemilikan) | A1 | Sedang |
| 3 | Rate limit undangan + jawaban seragam, lalu undangan `PENDING` dengan terima/tolak | S1, S2 | Sedang |
| 4 | Push notification lewat Expo Push API | M1 | Sedang |
| 5 | Hosting backend dengan HTTPS (juga menyelesaikan M2) | O1, M2 | Sedang |
| 6 | Header CORS pada respons error | C2 | Kecil |
| 7 | CI minimal (backend, emulator, typecheck) | O3 | Kecil–sedang |
| 8 | Header keamanan di `vercel.json` + refresh token di cookie `HttpOnly` | S8 | Sedang |
| 9 | Verifikasi email saat registrasi | S3 | Sedang |
| 10 | Pemberitahuan privasi, persetujuan, dan retensi data | P1, O5 | Sedang |
| 11 | Sisanya: S4–S7, S10, A2, A4, C3–C5, I2, M3–M4, O7–O8 | — | Kecil per item |

---

## 11. Catatan untuk laporan auth yang sudah dikumpulkan

Laporan *Authentication & Authorization for Smart Pillbox for Elderly* ditulis sebelum beberapa perubahan di `main`. Bila laporan direvisi, bagian berikut perlu disesuaikan:

| Bagian | Di laporan | Di kode sekarang |
|---|---|---|
| 2.2 | Tidak menyebut pembatasan percobaan login; OTP "diblokir sementara" setelah 5 percobaan | Login dibatasi per email dan per IP (bawaan 10 dan 50 per 15 menit, `429`); register, lupa, dan reset password juga dibatasi. OTP yang salah 5 kali **dihanguskan**, bukan diblokir sementara |
| 2.3 | Klien meminta ID token Google lalu menukarnya ke Supabase | Di **web**, alurnya redirect OAuth dengan PKCE (`/auth/google-callback`, `exchangeCodeForSession`). Alur ID token hanya di aplikasi native |
| 2.4 | Rotasi refresh token | Tambahkan: rotasi berjalan dalam satu transaksi, dengan toleransi 10 detik untuk pengulangan yang sah |
| 2.6 | Batas 5 **kegagalan** per 300 detik per pasangan (user, pillbox) | 5 **percobaan** per 300 detik **per pillbox lintas semua user**, dihitung sebelum scrypt dan disimpan di database. Percobaan *join* oleh orang yang belum menjadi caregiver punya penghitung terpisah |
| 3 | "Patient-Centered RBAC" | Bukan istilah baku; lebih tepat "RBAC dengan role per lansia" |
| 4.1 | Gerbang 1 hanya memeriksa tanda tangan dan `exp` | Gerbang 1 juga memastikan user masih terdaftar (cache maksimal 30 detik) |
| Umum | Tidak ada bagian keterbatasan | Pertimbangkan menambah S1–S3, S8, dan S9 dari audit ini |
| Halaman 1 | "yang1" | Salah ketik |
