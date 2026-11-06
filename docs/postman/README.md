# PillCare API — Postman Collection

Referensi lengkap seluruh endpoint HTTP PillCare dalam format Postman Collection v2.1.

| File | Isi |
|---|---|
| `PillCare.postman_collection.json` | 70 request dalam 13 folder: 56 operasi backend FastAPI dan 14 operasi server auth |
| `PillCare-Local.postman_environment.json` | Environment lokal: URL server dan variabel rahasia (kosong) |
| `build_postman.py` | Generator koleksi dari skema OpenAPI backend |

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

## Membangkitkan ulang

Koleksi diturunkan dari kode, jadi bangkitkan ulang setiap kali API berubah. Dari root repositori:

```bash
Backend/.venv/Scripts/python.exe docs/postman/build_postman.py
```

Di macOS/Linux, gunakan `Backend/.venv/bin/python`. Generator membaca `app.openapi()` (tanpa menjalankan server atau
menyentuh database) dan **gagal** bila ada operasi baru yang belum didokumentasikan di `build_postman.py`, atau bila
dokumentasi merujuk operasi yang sudah tidak ada.

Endpoint server auth (Expo API routes) tidak memiliki skema OpenAPI, sehingga dipelihara manual di `AUTH_OPS`.

## Prinsip penyusunan

| Prinsip | Penerapan | Rujukan |
|---|---|---|
| Kelengkapan dan kejelasan adalah masalah dokumentasi paling berat | Semua 70 endpoint tercakup; setiap request mencantumkan tujuan, hak akses, aturan bisnis, dan tabel error | Uddin & Robillard (2015) |
| Contoh pemakaian mempercepat pemakaian REST API | Setiap request punya body contoh terisi dan contoh respons sukses serta error | Sohan et al. (2017); Robillard & DeLine (2011) |
| Dokumentasi maksud dan pemetaan skenario | Deskripsi folder menjelaskan konsep (penilaian dosis, sinkronisasi konfigurasi, peran); deskripsi koleksi memuat alur umum | Robillard & DeLine (2011) |
| Hindari dokumentasi usang, tidak konsisten, dan bertele-tele | Dibangkitkan dari OpenAPI pada commit tertentu; satu request per operasi, varian ditaruh sebagai contoh respons; error umum (401) dijelaskan sekali di tingkat koleksi | Uddin & Robillard (2015); Aghajani et al. (2019) |
| Pengguna perlu cepat mencapai respons sukses pertama, dan autentikasi harus jelas | Bagian *Mulai dalam 3 langkah*; autentikasi diatur di tingkat koleksi dan folder lalu diwariskan | Postman Learning Center |
| Rahasia tidak ikut dibagikan | Semua nilai rahasia kosong dan bertipe *secret* | Postman Learning Center |

### Rujukan

- Robillard, M. P., & DeLine, R. (2011). A field study of API learning obstacles. *Empirical Software Engineering*, 16(6), 703–732.
- Uddin, G., & Robillard, M. P. (2015). How API documentation fails. *IEEE Software*, 32(4), 68–75.
- Sohan, S. M., Maurer, F., Anslow, C., & Robillard, M. P. (2017). A study of the effectiveness of usage examples in REST API documentation. *IEEE VL/HCC 2017*, 53–61.
- Meng, M., Steinhardt, S., & Schubert, A. (2018). Application programming interface documentation: What do software developers want? *Journal of Technical Writing and Communication*, 48(3), 295–330.
- Aghajani, E., et al. (2019). Software documentation issues unveiled. *ICSE 2019*.
- Postman Learning Center: *Document a collection*; *Curate collections for the Postman API Network*.
