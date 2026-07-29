# Announcement Server

Server pengumuman Text-to-Speech offline yang siap produksi untuk sistem Public Address (PA/TOA) berbasis Windows. Server ini menyediakan HTTP API untuk mengantrekan pengumuman, mensintesis suara secara lokal (tanpa ketergantungan cloud), memutar audio ke perangkat output yang dipilih, serta mendukung banyak zona audio independen, pengumuman terjadwal, dan status real-time lewat WebSocket.

## Fitur

- **Text-to-Speech lewat [Piper](https://github.com/rhasspy/piper)** — sintesis suara sepenuhnya offline dengan voice, kecepatan, pitch, dan volume yang dapat dikonfigurasi.
- **Playback audio statis** — memutar file suara yang sudah ada (bell, alarm, jingle, WAV/MP3/dst) berdampingan dengan pengumuman TTS.
- **Antrean berprioritas** — pengumuman diproses berdasarkan urutan prioritas (`urgent` > `high` > `normal` > `low`), lalu FIFO.
- **Audio multi-zona** — menjalankan beberapa jalur audio independen (queue + worker + output device) dari satu instance server, masing-masing dengan volume sendiri.
- **Scheduler** — memicu pengumuman otomatis secara harian, mingguan, atau sekali waktu.
- **Status WebSocket real-time** — update berbasis push (tanpa polling) untuk perubahan antrean, status playback, dan item yang selesai diproses.
- **Endpoint dashboard/monitoring** — status, riwayat, dan metrik teragregasi untuk dashboard eksternal.
- **Cache audio** — audio hasil sintesis dan konversi disimpan di cache (berbasis SHA256) sehingga pengumuman yang berulang tidak perlu menjalankan ulang TTS/ffmpeg.
- **Graceful degradation** — server tetap dapat berjalan dan melayani sebagian besar endpoint meskipun Piper, ffmpeg, atau driver audio belum terpasang/salah konfigurasi.
- **Dukungan Windows Service** — dapat dipasang sebagai Windows Service yang auto-start dan auto-restart lewat NSSM.

## Kebutuhan

- Python 3.11+ (Windows 10/11 direkomendasikan untuk produksi; Linux/macOS didukung untuk development)
- Binary [Piper TTS](https://github.com/rhasspy/piper) + minimal satu voice model (wajib untuk pengumuman TTS — lihat [Setup Piper](#setup-piper-tts-engine))
- [ffmpeg](https://ffmpeg.org/download.html) (opsional — hanya dibutuhkan untuk memutar file audio statis yang belum berformat `.wav`)
- Perangkat output audio yang tersedia (opsional — server tetap berjalan tanpanya, namun endpoint playback tidak akan berfungsi)

## Instalasi

### Windows

```bat
run.bat
```

Script ini akan membuat virtual environment (`venv/`), menginstall dependency dari `requirements.txt`, dan menjalankan server di `http://0.0.0.0:8000`.

### Linux / macOS (development)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)/src
uvicorn announcement_server.main:app --reload
```

## Setup Piper (TTS Engine)

Piper tidak disertakan dalam repository ini dan harus diunduh secara terpisah:

1. Unduh binary Piper untuk Windows dari [halaman rilis Piper](https://github.com/rhasspy/piper/releases).
2. Ekstrak sehingga `piper.exe` berada di `engines/piper/piper.exe` (relatif terhadap root project), atau arahkan ke lokasi lain lewat `tts.piper_binary_path` di `config/config.yaml`.
3. Unduh minimal satu voice model (mis. `en_US-lessac-medium`) dari [daftar voice Piper](https://github.com/rhasspy/piper/blob/master/VOICES.md). Setiap voice terdiri dari dua file: `<voice>.onnx` dan `<voice>.onnx.json`.
4. Taruh kedua file tersebut di `engines/piper/models/`, atau arahkan ke direktori lain lewat `tts.piper_models_dir`.
5. Set `tts.default_voice` di `config/config.yaml` agar sesuai dengan nama voice yang diunduh (tanpa ekstensi file).

Jika Piper belum ter-setup, server tetap berjalan normal — hanya pengumuman yang dikirim lewat `POST /speak` yang akan gagal (dengan `error_message` yang jelas) saat diproses.

## Setup ffmpeg (opsional)

File audio statis yang sudah berformat `.wav` diputar langsung tanpa dependency tambahan apa pun. ffmpeg hanya dibutuhkan untuk mengonversi format lain (mis. MP3) ke WAV secara otomatis.

1. Unduh ffmpeg untuk Windows dari [halaman rilis resmi](https://www.gyan.dev/ffmpeg/builds/) atau [ffmpeg.org](https://ffmpeg.org/download.html).
2. Tambahkan folder yang berisi `ffmpeg.exe` ke `PATH` sistem, atau set path absolut lewat `announcement.ffmpeg_binary_path` di `config/config.yaml`.
3. Taruh file audio (bell, alarm, jingle, dst) di direktori yang dikonfigurasi lewat `announcement.sounds_dir` (default: `sounds/`).

Jika ffmpeg belum ter-setup, server tetap berjalan normal — hanya pengumuman audio non-WAV yang akan gagal dengan pesan error yang jelas.

## Konfigurasi

File konfigurasi utama ada di [`config/config.yaml`](config/config.yaml). Setiap nilai juga dapat di-override lewat environment variable dengan prefix `APP_`, menggunakan `__` sebagai nested delimiter, contoh:

```bash
APP_SERVER__PORT=9000
APP_LOGGING__LEVEL=DEBUG
```

Environment variable selalu memiliki prioritas lebih tinggi daripada `config.yaml`, yang pada gilirannya meng-override nilai default bawaan.

Bagian konfigurasi utama:

| Bagian | Fungsi |
|---|---|
| `app` | Nama aplikasi, deskripsi, environment (`development`/`staging`/`production`) |
| `server` | Host, port, reload, jumlah worker, CORS origins |
| `logging` | Level log, direktori, nama file, rotasi |
| `tts` | Path engine Piper, direktori model, voice default, cache, perilaku retry |
| `playback` | Output device default, jeda antar pengumuman |
| `queue` | Jumlah maksimum item pending, riwayat maksimum yang disimpan di memory |
| `announcement` | Direktori file suara statis, path ffmpeg, cache konversi |
| `zones` | Zona audio tambahan (device, volume, enabled) |
| `scheduler` | Interval polling, timezone |
| `schedules` | Jadwal pengumuman statis yang didefinisikan sebelumnya |
| `maintenance` | Pembersihan cache saat startup, timeout graceful shutdown |

Zona dan jadwal yang didefinisikan di `config.yaml` otomatis dibuat saat startup, tetapi juga bisa dibuat, diubah, atau dihapus saat runtime lewat REST API tanpa perlu me-restart server.

## Konfigurasi Port

Port HTTP default adalah:

```
http://localhost:8000
```

Port dibaca dari `server.port` di `config/config.yaml`, dan dapat diubah lewat salah satu cara berikut:

**1. Edit `config/config.yaml`:**

```yaml
server:
  port: 8080
```

**2. Set environment variable `APP_SERVER__PORT`** (meng-override `config.yaml`):

```bash
# Linux / macOS
export APP_SERVER__PORT=8080
uvicorn announcement_server.main:app

# Windows (cmd)
set APP_SERVER__PORT=8080
python -m uvicorn announcement_server.main:app --host 0.0.0.0 --port 8080
```

**3. Berikan flag `--port` langsung ke uvicorn** (saat menjalankan secara manual, bukan lewat `run.bat`):

```bash
uvicorn announcement_server.main:app --host 0.0.0.0 --port 8080
```

Hasil dengan port kustom:

```
http://localhost:8080
```

> Catatan: `run.bat` dan `install_service.bat` menjalankan uvicorn dengan `--port 8000` yang di-hardcode. Untuk memakai port berbeda lewat script ini, ubah nilai `--port` di dalam script, atau set `server.port` di `config/config.yaml` dan hapus flag `--port` agar uvicorn memakai nilai dari konfigurasi.

## Menjalankan

### Development

```bash
uvicorn announcement_server.main:app --reload
```

### Produksi (Windows, foreground)

```bat
run.bat
```

### Produksi (Windows Service, lewat NSSM)

Menjalankan server sebagai Windows Service yang otomatis start saat boot dan restart otomatis jika crash.

1. Unduh [NSSM](https://nssm.cc/download) dan salin `nssm.exe` ke `tools\nssm\nssm.exe` (lihat `tools/nssm/README.md`).
2. Jalankan sebagai **Administrator**: `install_service.bat` — menyiapkan virtual environment, menginstall dependency, lalu menginstall & menjalankan service `AnnouncementServer`.
3. `restart_service.bat` — merestart service (mis. setelah mengubah `config/config.yaml`).
4. `uninstall_service.bat` — menghentikan dan menghapus service (virtual environment/konfigurasi tidak ikut terhapus).

Cek status: `sc query AnnouncementServer`
Log service: `logs\service_stdout.log` / `logs\service_stderr.log`
Log aplikasi: `logs\announcement_server.log`

## Dokumentasi API

Setelah server berjalan, dokumentasi API interaktif tersedia di:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI schema: `http://localhost:8000/openapi.json`

## Penggunaan

### Menambahkan pengumuman ke antrean

`POST /speak` menambahkan pengumuman ke antrean. Endpoint ini mendukung dua sumber audio lewat field `type`:

**Text-to-speech (default):**

```json
{
  "type": "tts",
  "text": "Nomor antrean A001, silakan menuju loket 3.",
  "priority": "normal",
  "voice": null,
  "speed": 1.0,
  "pitch": 1.0,
  "volume": 1.0
}
```

**File audio statis:**

```json
{
  "type": "audio",
  "file": "bell.mp3",
  "priority": "high"
}
```

Catatan field:
- `type`: `tts` (default) atau `audio`.
- `text`: wajib diisi untuk `type=tts`. Opsional untuk `type=audio` — jika kosong, teks tampilan seperti `"[audio] <file>"` dibuat otomatis.
- `file`: wajib diisi untuk `type=audio` — path relatif terhadap `announcement.sounds_dir` (default `sounds/`). Path yang mencoba keluar dari direktori ini (mis. `"../../secret.txt"`) akan ditolak.
- `priority`: `urgent` | `high` | `normal` (default) | `low`.
- `voice`: nama voice Piper (mis. `en_US-lessac-medium`). Biarkan `null` untuk memakai `tts.default_voice`. Diabaikan untuk `type=audio`.
- `speed`: 0.5–2.0 (1.0 = normal). Diabaikan untuk `type=audio`.
- `pitch`: 0.5–2.0 (1.0 = normal). Diabaikan untuk `type=audio`.
- `volume`: 0.0–2.0 (1.0 = normal). Berlaku untuk `tts` maupun `audio`.

Response (`201 Created`):

```json
{
  "id": "a1b2c3d4-...",
  "type": "tts",
  "text": "Nomor antrean A001, silakan menuju loket 3.",
  "file": null,
  "priority": "normal",
  "status": "pending",
  "created_at": "2026-07-29T10:00:00Z",
  "updated_at": "2026-07-29T10:00:00Z",
  "error_message": null,
  "voice": "en_US-lessac-medium",
  "speed": 1.0,
  "pitch": 1.0,
  "volume": 1.0,
  "audio_file_path": null,
  "cache_hit": null,
  "position": 1
}
```

Pemrosesan (sintesis/konversi + playback) berjalan secara **asinkron** di background. Response `201` hanya berarti item berhasil diterima ke dalam antrean — pantau progresnya lewat `GET /queue?status=completed` atau `GET /queue?status=failed`.

### Manajemen antrean

| Method | Path | Deskripsi |
|---|---|---|
| `POST` | `/speak` | Menambahkan pengumuman ke antrean (zona `main`) |
| `GET` | `/queue` | Melihat isi antrean (default: hanya item aktif — pending/processing) |
| `DELETE` | `/queue/{item_id}` | Membatalkan item yang masih pending |
| `POST` | `/clear` | Membatalkan seluruh item pending |

`GET /queue` menerima query parameter opsional `status` untuk melihat status tertentu, termasuk riwayat completed/failed/cancelled (dibatasi oleh `queue.max_history`).

### Kontrol playback

| Method | Path | Deskripsi |
|---|---|---|
| `GET` | `/devices` | Melihat daftar output audio device yang tersedia |
| `POST` | `/device` | Memilih output device aktif |
| `POST` | `/pause` | Menjeda playback yang sedang berjalan |
| `POST` | `/resume` | Melanjutkan playback yang dijeda |
| `POST` | `/stop` | Menghentikan playback (idempotent) |

Contoh response `GET /devices`:

```json
{
  "devices": [
    {"id": 0, "name": "Speaker (Realtek Audio)", "max_output_channels": 2, "default_samplerate": 44100.0, "is_default": true},
    {"id": 3, "name": "Speaker TOA (USB Audio)", "max_output_channels": 2, "default_samplerate": 48000.0, "is_default": false}
  ],
  "count": 2
}
```

`/device`, `/pause`, `/resume`, dan `/stop` semuanya mengembalikan format yang sama:

```json
{
  "state": "playing",
  "current_file": "cache/audio/7f4f14e....wav",
  "selected_device_id": 3
}
```

`state` bernilai salah satu dari `idle`, `playing`, `paused`. Jika tidak ada driver audio yang terdeteksi di mesin, endpoint ini akan mengembalikan error `502` yang jelas, tanpa menghalangi bagian server lainnya untuk tetap berjalan.

### Zona (audio multi-channel)

Setiap zona adalah jalur audio independen — memiliki antrean, worker, dan perangkat playback sendiri. Zona `main` selalu ada dan tidak dapat dihapus; endpoint level atas `/speak`, `/queue`, `/clear`, `/devices`, `/device`, `/pause`, `/resume`, `/stop` selalu beroperasi pada zona ini.

| Method | Path | Deskripsi |
|---|---|---|
| `GET` | `/zones` | Melihat daftar seluruh zona beserta status runtime-nya |
| `POST` | `/zones` | Membuat zona baru |
| `PUT` | `/zones/{name}` | Memperbarui zona (pembaruan parsial) |
| `DELETE` | `/zones/{name}` | Menghapus zona (zona `main` dilindungi) |
| `GET` | `/zones/{name}/queue` | Melihat antrean milik satu zona |
| `POST` | `/zones/{name}/device` | Memilih output device untuk satu zona |
| `POST` | `/zones/{name}/speak` | Mengirim pengumuman ke satu zona |

Contoh — membuat zona:

```json
{
  "name": "lobby",
  "device_id": null,
  "volume": 1.0,
  "enabled": true
}
```

Contoh — mengirim pengumuman ke zona tertentu:

```bash
curl -X POST http://localhost:8000/zones/lobby/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Selamat datang di lobby"}'
```

`volume` pada zona adalah gain per-channel yang diterapkan saat playback (seperti volume knob per-channel amplifier), terpisah dari `volume` per-item yang dikirim lewat `POST /speak`.

### Scheduler

Memicu pengumuman otomatis secara berkala atau sekali waktu.

| Method | Path | Deskripsi |
|---|---|---|
| `GET` | `/scheduler` | Melihat daftar seluruh jadwal |
| `POST` | `/scheduler` | Membuat jadwal baru |
| `GET` | `/scheduler/{id}` | Melihat detail satu jadwal |
| `PUT` | `/scheduler/{id}` | Memperbarui jadwal (pembaruan parsial) |
| `DELETE` | `/scheduler/{id}` | Menghapus jadwal |
| `POST` | `/scheduler/{id}/trigger` | Memicu jadwal segera, tanpa memengaruhi jadwal otomatis berikutnya |

Contoh — jadwal harian:

```json
{
  "name": "Bell Masuk",
  "zone": "main",
  "recurrence": "daily",
  "time_of_day": "07:00",
  "announcement": { "type": "audio", "file": "bell.wav", "priority": "high" }
}
```

Contoh — jadwal mingguan (Senin–Jumat):

```json
{
  "name": "Istirahat Siang",
  "recurrence": "weekly",
  "time_of_day": "12:00",
  "days_of_week": [0, 1, 2, 3, 4],
  "announcement": { "type": "tts", "text": "Waktunya istirahat siang." }
}
```

Contoh — jadwal sekali waktu:

```json
{
  "name": "Pengumuman Khusus",
  "recurrence": "once",
  "time_of_day": "09:00",
  "run_date": "2026-08-17",
  "announcement": { "type": "tts", "text": "Ini adalah pengumuman khusus." }
}
```

- `recurrence`: `daily` | `weekly` | `once`.
- `time_of_day`: format `"HH:MM"` atau `"HH:MM:SS"` (24 jam).
- `days_of_week`: wajib untuk `weekly` — daftar angka `0` (Senin) sampai `6` (Minggu).
- `run_date`: wajib untuk `once` — format `"YYYY-MM-DD"`. Ditolak (`422`) jika sudah berlalu.
- `zone`: nama zona tujuan (default `"main"`).

Jadwal `once` otomatis dinonaktifkan setelah terpicu satu kali. Perilaku timezone diatur lewat `scheduler.timezone` di `config/config.yaml` — `"local"` (default) memakai jam sistem apa adanya, atau isi dengan nama zona IANA eksplisit (mis. `"Asia/Jakarta"`).

### Status WebSocket

Hubungkan ke `ws://localhost:8000/ws/status` untuk mendapatkan update status real-time berbasis push (tanpa polling). Setelah terhubung, client menerima satu snapshot seluruh zona, diikuti event-event berikutnya saat terjadi.

Format pesan:

```json
{ "event": "<nama_event>", "timestamp": "2026-07-29T10:00:00+00:00", "data": { ... } }
```

| Event | Kapan dikirim |
|---|---|
| `snapshot` | Sekali, tepat setelah koneksi terbuka |
| `queue_changed` | Setiap perubahan status item antrean |
| `speaking` | Playback mulai berjalan |
| `idle` | Playback berhenti atau selesai |
| `pause` | Playback dijeda |
| `resume` | Playback dilanjutkan |
| `finished` | Satu item selesai diproses (completed atau failed) |

Setiap event kecuali `snapshot` memiliki field `zone`, karena satu koneksi mem-broadcast event dari seluruh zona.

Contoh (browser console):

```js
const ws = new WebSocket("ws://localhost:8000/ws/status");
ws.onmessage = (msg) => console.log(JSON.parse(msg.data));
```

### Dashboard & monitoring

Endpoint read-only untuk dashboard dan tools monitoring eksternal.

| Method | Path | Deskripsi |
|---|---|---|
| `GET` | `/status` | Snapshot lengkap: status queue/worker/device/playback per zona, statistik cache, jumlah client WebSocket, uptime |
| `GET` | `/history` | Pengumuman yang sudah selesai (completed/failed/cancelled) lintas zona, terbaru dulu |
| `GET` | `/metrics` | Ringkasan angka: jumlah item per status, jumlah zona, jadwal aktif, client WebSocket, cache, penggunaan memory |
| `GET` | `/health` | Health check ringan untuk monitoring/watchdog |
| `POST` | `/maintenance/cache/cleanup` | Menghapus file cache TTS/announcement yang lebih tua dari batas usia yang dikonfigurasi (atau dikirim lewat request) |

`GET /history` mendukung query parameter opsional: `zone` (batasi ke satu zona), `status` (default: seluruh status final), `limit` (default 100, maksimum 1000).

## Struktur Project

```
announcement-server/
├── src/announcement_server/
│   ├── main.py                    # Application factory (create_app) + entry point ASGI
│   ├── core/                      # Settings, logging, exceptions, kontrak event
│   ├── api/
│   │   ├── deps.py                # Dependency injection providers
│   │   └── v1/                    # Router: health, queue, playback, zones, scheduler, websocket, dashboard, maintenance
│   ├── queueing/                  # Sistem antrean: models, manager, worker, pipeline processing
│   ├── announcement/              # Resolusi audio statis (konversi ffmpeg + cache)
│   ├── tts/                       # Abstraksi TTS engine, implementasi Piper, post-processing audio, cache
│   ├── playback/                  # Manajemen audio device dan kontrol playback
│   ├── zones/                     # Orkestrasi multi-zona
│   ├── scheduler/                 # Penjadwalan pengumuman berbasis waktu
│   ├── websocket/                 # Manajemen koneksi WebSocket
│   └── schemas/                   # Model request/response
├── config/config.yaml             # File konfigurasi utama
├── engines/piper/                 # (dibuat manual) binary + voice model Piper — lihat Setup Piper
├── sounds/                        # (dibuat manual) file audio statis — lihat announcement.sounds_dir
├── cache/audio/                   # (dibuat otomatis) cache audio TTS, dipakai bersama seluruh zona
├── cache/announcement_audio/      # (dibuat otomatis) cache hasil konversi ffmpeg
├── scripts/manual_test_playback.py# Alat bantu verifikasi playback manual (bukan bagian dari API)
├── logs/                          # Log aplikasi dan service
├── tests/                         # Test suite
├── requirements.txt
├── run.bat                        # Windows: setup + jalankan di foreground
├── install_service.bat            # Windows: install sebagai Windows Service (NSSM)
├── restart_service.bat            # Windows: restart Windows Service
└── uninstall_service.bat          # Windows: hapus Windows Service
```

## Menjalankan Test

```bash
pip install -r requirements.txt
export PYTHONPATH=$(pwd)/src
pytest -v
```

## Troubleshooting

- **Item `POST /speak` gagal dengan error TTS** — Piper belum terpasang atau salah konfigurasi. Periksa `tts.piper_binary_path` dan `tts.piper_models_dir` di `config/config.yaml`, dan pastikan nama voice di `tts.default_voice` sesuai dengan file model yang diunduh.
- **Pengumuman bertipe audio gagal untuk file non-WAV** — ffmpeg belum terpasang atau tidak ada di `PATH`. File `.wav` selalu berfungsi tanpa ffmpeg.
- **`/devices`, `/device`, `/pause`, `/resume`, `/stop` mengembalikan error** — tidak ada perangkat/driver output audio yang terdeteksi saat server startup. Endpoint lain tetap berfungsi normal.
- **Pengumuman terjadwal tidak terpicu pada waktu lokal yang diharapkan** — periksa `scheduler.timezone` di `config/config.yaml`. Jika memakai nama zona IANA eksplisit (mis. `"Asia/Jakarta"`) di Windows, pastikan paket `tzdata` sudah terpasang (sudah termasuk di `requirements.txt`).
- **Perubahan port tidak berpengaruh** — jika menjalankan lewat `run.bat` atau `install_service.bat`, port dikirim secara eksplisit lewat flag command-line dan meng-override `config.yaml`; ubah script tersebut atau hapus flag-nya seperti dijelaskan di [Konfigurasi Port](#konfigurasi-port).

## Lisensi

Repository ini belum menyertakan file lisensi. Hubungi maintainer project untuk ketentuan penggunaan.
