# PillCare API — Postman Collection

Referensi lengkap seluruh endpoint HTTP PillCare dalam format Postman Collection v2.1.

| File | Isi |
|---|---|
| `PillCare.postman_collection.json` | 72 request dalam 14 folder: 56 operasi backend FastAPI, 14 operasi server auth, dan 2 request di folder *Access control demo* |
| `PillCare-Local.postman_environment.json` | Environment lokal: URL server dan variabel rahasia (kosong) |

> **Status per 24 Nov 2026.** Backend saat ini punya 57 operasi HTTP. Satu belum masuk koleksi: `DELETE /api/v1/devices/{device_id}/alarm` (hentikan alarm, ditambahkan pada perbaikan *robustness hardening*). Tambahkan ke folder *Devices* bila koleksi diperbarui.
>
> Fitur Roles (24 Nov, belum di-commit) menambah 6 operasi yang juga belum ada di koleksi: `PUT /elderly/{id}/caregivers/{caregiver_id}`, `POST`/`GET /elderly/{id}/invitations`, `DELETE /elderly/{id}/invitations/{invitation_id}`, `POST /invitations/preview`, `POST /invitations/accept`. Bentuk request dan error ada di `docs/ROLES_FEATURE_PLAN.md`, "Baris API list yang perlu ditambahkan".

## Memakai koleksi

1. Postman → **Import** → pilih kedua file JSON.
2. Pilih environment **PillCare · Local** di kanan atas, lalu isi nilai *Current value*:

   | Variabel | Isi |
   |---|---|
   | `email`, `password` | Akun caregiver utama yang memiliki perangkat/jadwal target |
   | `other_caregiver_email`, `other_caregiver_password` | Akun caregiver kedua yang tidak memiliki akses ke lansia target |
   | `device_pin` | PIN 4 digit perangkat (untuk pairing, join, kalibrasi, buka ulang kompartemen) |
   | `device_key` | Secret perangkat (folder *Device Protocol*). Terisi otomatis oleh *Provision device* |
   | `provisioning_token` | Token provisioning server (folder *Provisioning*) |
   | `invitee_email` | Email caregiver lain untuk *Add caregiver* |

3. Jalankan **Authentication › Log in** sebagai akun utama. Jalankan **Devices › List devices** lalu **Schedules › List slot schedules** untuk mengisi otomatis `device_id` dan `schedule_id` milik akun utama.
4. Untuk demo isolasi akses, isi akun kedua pada `other_caregiver_email` dan `other_caregiver_password`, lalu jalankan **Access control demo › Log in as unrelated caregiver** diikuti **Try to update the first caregiver schedule**. Hasil yang diharapkan: `404 NOT_FOUND`; token akun kedua disimpan terpisah sehingga token utama tetap aktif. Jangan join akun kedua ke lansia target karena itu mengubah skenario menjadi anggota read-only (PEMANTAU), yang semestinya mendapat `403 FORBIDDEN` saat mengubah jadwal.

Deskripsi koleksi (tab *Overview*) memuat autentikasi, konvensi, format error, alur umum, dan kanal WebSocket.

## Memperbarui koleksi

Koleksi awalnya dibangkitkan dari `app.openapi()` backend oleh skrip `build_postman.py`, tetapi skrip itu **tidak pernah di-commit** ke repositori. Sejak itu koleksi diperbarui manual (misalnya folder *Access control demo*). Saat API berubah:

1. Tambahkan atau ubah request di Postman, lalu **Export** sebagai Collection v2.1 ke file ini.
2. Cocokkan daftar operasi dengan route backend (`Backend/app/api/routes/*.py`) dan route server auth (`Mobile/src/app/api/**`). Endpoint server auth tidak punya skema OpenAPI, jadi selalu dipelihara manual.
3. Perbarui jumlah request di tabel atas.

## Prinsip penyusunan

| Prinsip | Penerapan | Rujukan |
|---|---|---|
| Kelengkapan dan kejelasan adalah masalah dokumentasi paling berat | 70 dari 71 operasi tercakup (lihat status di atas); setiap request mencantumkan tujuan, hak akses, aturan bisnis, dan tabel error | Uddin & Robillard (2015) |
| Contoh pemakaian mempercepat pemakaian REST API | Setiap request punya body contoh terisi dan contoh respons sukses serta error | Sohan et al. (2017); Robillard & DeLine (2011) |
| Dokumentasi maksud dan pemetaan skenario | Deskripsi folder menjelaskan konsep (penilaian dosis, sinkronisasi konfigurasi, peran); deskripsi koleksi memuat alur umum | Robillard & DeLine (2011) |
| Hindari dokumentasi usang, tidak konsisten, dan bertele-tele | Awalnya dibangkitkan dari OpenAPI, kini dicocokkan manual ke route (lihat *Memperbarui koleksi*); satu request per operasi, varian ditaruh sebagai contoh respons; error umum (401) dijelaskan sekali di tingkat koleksi | Uddin & Robillard (2015); Aghajani et al. (2019) |
| Pengguna perlu cepat mencapai respons sukses pertama, dan autentikasi harus jelas | Bagian *Mulai dalam 3 langkah*; autentikasi diatur di tingkat koleksi dan folder lalu diwariskan | Postman Learning Center |
| Rahasia tidak ikut dibagikan | Semua nilai rahasia kosong dan bertipe *secret* | Postman Learning Center |

### Rujukan

- Robillard, M. P., & DeLine, R. (2011). A field study of API learning obstacles. *Empirical Software Engineering*, 16(6), 703–732.
- Uddin, G., & Robillard, M. P. (2015). How API documentation fails. *IEEE Software*, 32(4), 68–75.
- Sohan, S. M., Maurer, F., Anslow, C., & Robillard, M. P. (2017). A study of the effectiveness of usage examples in REST API documentation. *IEEE VL/HCC 2017*, 53–61.
- Meng, M., Steinhardt, S., & Schubert, A. (2018). Application programming interface documentation: What do software developers want? *Journal of Technical Writing and Communication*, 48(3), 295–330.
- Aghajani, E., et al. (2019). Software documentation issues unveiled. *ICSE 2019*.
- Postman Learning Center: *Document a collection*; *Curate collections for the Postman API Network*.
