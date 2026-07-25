# Announcement Server

Production Ready Text-to-Speech Announcement Server berbasis Python untuk Windows.
Menerima request HTTP, mengantrekan pengumuman, mengubah teks menjadi suara
(offline), memutar audio ke sistem TOA, serta mendukung Public Address (PA)
multi-zona.

> **Status:** Phase 8 — Scheduler. Server kini dapat memicu pengumuman otomatis berbasis waktu (Daily/Weekly/One Time) lewat REST API `/scheduler`, meng-enqueue lewat mekanisme antrean yang sudah ada (Phase 2/6/7) tanpa jalur pemrosesan baru. Endpoint & perilaku Phase 1-7 tidak berubah. Lihat [Endpoint Scheduler (Phase 8)](#endpoint-scheduler-phase-8) di bawah.

## Requirements

- Python 3.11+
- Windows 10/11 (development/production) — kompatibel juga di Linux/macOS untuk development.
- **Piper TTS** (untuk fitur Text-to-Speech, Phase 3 ke atas) — lihat bagian [Setup Piper (TTS Engine)](#setup-piper-tts-engine) di bawah.
- **ffmpeg** (opsional, Phase 7) — hanya dibutuhkan untuk memutar file audio statis berformat SELAIN `.wav` (mis. MP3). Lihat [Setup ffmpeg (opsional, Announcement Engine)](#setup-ffmpeg-opsional-announcement-engine) di bawah.

## Setup Piper (TTS Engine)

Server ini memakai [Piper](https://github.com/rhasspy/piper) sebagai engine TTS offline default. Piper **tidak disertakan** dalam repository ini (ukurannya besar & berlisensi terpisah) — unduh secara manual:

1. Unduh binary Piper untuk Windows dari [rilis resmi Piper](https://github.com/rhasspy/piper/releases) (pilih `piper_windows_amd64.zip` atau setara).
2. Ekstrak sehingga `piper.exe` berada di `engines/piper/piper.exe` (relatif terhadap root project), atau sesuaikan path lewat `tts.piper_binary_path` di `config/config.yaml`.
3. Unduh minimal satu voice model (mis. `en_US-lessac-medium`) dari [halaman voices Piper](https://github.com/rhasspy/piper/blob/master/VOICES.md) — setiap voice terdiri dari 2 file: `<voice>.onnx` dan `<voice>.onnx.json`.
4. Taruh keduanya di `engines/piper/models/`, atau sesuaikan lewat `tts.piper_models_dir`.
5. Set `tts.default_voice` di `config/config.yaml` sesuai nama voice yang diunduh (tanpa ekstensi).

> Jika Piper belum ter-setup, server tetap bisa berjalan normal (endpoint `/health`, `/queue`, dll tetap berfungsi) — hanya item yang dikirim lewat `POST /speak` yang akan berstatus `failed` saat diproses, dengan `error_message` yang menjelaskan penyebabnya. Ini disengaja (graceful degradation) agar satu komponen yang belum siap tidak menjatuhkan seluruh server.

## Setup ffmpeg (opsional, Announcement Engine)

Sejak **Phase 7**, server dapat memutar file audio statis (bell/alarm/jingle) lewat `POST /speak` dengan `{"type": "audio", "file": "..."}` (lihat [Endpoint Queue System](#endpoint-queue-system-phase-2--tts-phase-3--announcement-engine-phase-7) di bawah). File berformat `.wav` diputar LANGSUNG tanpa dependensi tambahan apa pun. **ffmpeg hanya dibutuhkan untuk format lain (mis. MP3)** — dipakai untuk mengonversi file tsb ke WAV secara otomatis.

1. Unduh ffmpeg untuk Windows dari [rilis resmi ffmpeg (gyan.dev builds)](https://www.gyan.dev/ffmpeg/builds/) atau [ffmpeg.org](https://ffmpeg.org/download.html).
2. Ekstrak lalu tambahkan folder `bin/` (berisi `ffmpeg.exe`) ke PATH sistem, ATAU set path absolut lewat `announcement.ffmpeg_binary_path` di `config/config.yaml`.
3. Simpan file audio (bell/alarm/jingle/dll) di direktori `sounds/` (lihat `announcement.sounds_dir`).

> Jika ffmpeg belum ter-setup, server tetap berjalan normal — file `.wav` tetap bisa diputar tanpa masalah. Hanya item bertipe `audio` dengan sumber SELAIN `.wav` yang akan berstatus `failed` saat diproses (`error_message` menjelaskan bahwa ffmpeg tidak ditemukan). Konsisten dengan prinsip graceful degradation yang sama seperti Piper di atas.

## Instalasi & Menjalankan (Windows)

```bat
run.bat
```

Script ini akan otomatis:
1. Membuat virtual environment (`venv/`) jika belum ada.
2. Menginstall dependencies dari `requirements.txt`.
3. Menjalankan server di `http://0.0.0.0:8000`.

## Instalasi & Menjalankan (manual / Linux / macOS, untuk development)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)/src
uvicorn announcement_server.main:app --reload
```

## Dokumentasi API

Setelah server berjalan:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI schema: <http://localhost:8000/openapi.json>

## Endpoint Queue System (Phase 2) + TTS (Phase 3) + Announcement Engine (Phase 7)

| Method | Path              | Deskripsi                                            |
|--------|-------------------|-------------------------------------------------------|
| POST   | `/speak`          | Menambahkan pengumuman baru ke antrean (TTS atau file audio statis, lihat `type`) |
| GET    | `/queue`          | Melihat antrean (default: item aktif — pending/processing) |
| DELETE | `/queue/{item_id}`| Membatalkan item PENDING                              |
| POST   | `/clear`          | Membatalkan seluruh item PENDING                       |

Sejak **Phase 7**, `POST /speak` mendukung DUA sumber audio lewat field `type`:

Contoh `type="tts"` (default — perilaku Phase 1-6 tanpa perubahan):

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

Contoh `type="audio"` (memutar file statis — bell/alarm/jingle/MP3/WAV apa pun):

```json
{
  "type": "audio",
  "file": "sounds/bell.mp3",
  "priority": "high"
}
```

- `type`: `tts` (default) | `audio`.
- `text`: WAJIB diisi (tidak boleh kosong) jika `type="tts"`. Untuk `type="audio"`, bersifat opsional — jika dikosongkan, otomatis diisi `"[audio] <file>"` supaya `GET /queue` tetap informatif.
- `file`: WAJIB diisi jika `type="audio"` — path RELATIF terhadap `announcement.sounds_dir` (default `sounds/`), mis. `"bell.mp3"` atau `"alarms/fire.wav"`. Path yang mencoba keluar dari direktori ini (mis. `"../../secret.txt"`) ditolak.
- `priority`: `urgent` | `high` | `normal` (default) | `low`.
- `voice`/`speed`/`pitch`: hanya relevan untuk `type="tts"` — diabaikan untuk `type="audio"`. Lihat penjelasan masing-masing di bawah.
- `voice`: nama voice Piper (mis. `en_US-lessac-medium`). Kosongkan (`null`) untuk memakai `tts.default_voice` dari config.
- `speed`: 0.5–2.0 (1.0 = normal). Dipetakan ke parameter native Piper `--length_scale`.
- `pitch`: 0.5–2.0 (1.0 = normal). **Catatan:** memakai teknik resampling sederhana yang turut memengaruhi tempo/durasi audio (lihat docstring `AudioProcessor.apply_pitch` untuk detail keterbatasan).
- `volume`: 0.0–2.0 (1.0 = normal). Berlaku untuk `type="tts"` maupun `type="audio"` (dipanggang ke audio saat sintesis TTS; untuk file statis, konversi ffmpeg TIDAK mengubah volume file asli — gunakan volume per-zone (Phase 6) untuk itu).

Response (`201 Created`) — ditambah field `type`/`file` sejak Phase 7:

```json
{
  "id": "a1b2c3d4-...",
  "type": "tts",
  "text": "Nomor antrean A001, silakan menuju loket 3.",
  "file": null,
  "priority": "normal",
  "status": "pending",
  "created_at": "2026-07-22T10:00:00Z",
  "updated_at": "2026-07-22T10:00:00Z",
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

> ⚠️ **Penting — seluruh pipeline (Cache/Generate + Playback) terjadi ASINKRON, untuk `type="tts"` MAUPUN `type="audio"`.** Response `201` di atas hanya berarti item berhasil masuk antrean, BUKAN berarti audio sudah jadi/diputar (`audio_file_path` masih `null`). QueueWorker memproses item di background lewat Worker Pipeline (Phase 5); pantau progres lewat `GET /queue?status=completed` (audio sudah jadi DAN — jika sistem audio tersedia — sudah selesai diputar, `audio_file_path` terisi) atau `GET /queue?status=failed` (lihat `error_message` — untuk `type="tts"` mis. voice tidak ditemukan/Piper belum ter-setup; untuk `type="audio"` mis. file tidak ditemukan atau `ffmpeg` belum ter-setup untuk format non-WAV — kegagalan playback TIDAK membuat item `failed`, lihat [Worker Pipeline (Phase 5)](#worker-pipeline-phase-5)).
>
> Audio hasil TTS disimpan sebagai file `.wav` di `tts.cache_dir` (default `cache/audio/`), dengan nama file = SHA256 dari kombinasi `engine + voice + text + speed + pitch + volume`. Mengirim teks yang sama persis dengan parameter sama akan langsung memakai cache (`cache_hit: true`) tanpa memanggil Piper ulang. Untuk `type="audio"`, file `.wav` diputar langsung (`cache_hit: true`, tanpa konversi), sedangkan format lain dikonversi ke WAV oleh `ffmpeg` dan hasilnya disimpan di `announcement.converted_cache_dir` (default `cache/announcement_audio/`) — lihat [Setup ffmpeg (opsional)](#setup-ffmpeg-opsional-announcement-engine).
>
> Audio tidak diputar sama sekali dalam pemrosesan Phase 3/7 sendiri. Sejak **Phase 5**, audio (baik dari TTS maupun file statis Phase 7) **otomatis diputar** ke output device aktif oleh Worker Pipeline setelah tahap Cache/Generate selesai — lihat [Worker Pipeline (Phase 5)](#worker-pipeline-phase-5).

`GET /queue` mendukung query param opsional `status` untuk melihat status
tertentu, termasuk riwayat (`completed`, `failed`, `cancelled`) selama
masih tersimpan di memory (dibatasi `queue.max_history` pada config).

## Endpoint Audio Playback (Phase 4)

| Method | Path       | Deskripsi                                            |
|--------|------------|--------------------------------------------------------|
| GET    | `/devices` | Melihat daftar output audio device yang tersedia       |
| POST   | `/device`  | Memilih output device aktif untuk playback              |
| POST   | `/pause`   | Menjeda playback yang sedang berjalan                    |
| POST   | `/resume`  | Melanjutkan playback yang dijeda                          |
| POST   | `/stop`    | Menghentikan playback sepenuhnya (idempotent)              |

> ⚠️ **Endpoint di sini murni kontrol manual** (pilih device, pause, resume,
> stop) — belum ada endpoint HTTP untuk "memutar file X" secara langsung
> (sesuai roadmap Phase 4). Sejak **Phase 5**, penyambungan hasil TTS ke
> playback terjadi **otomatis di background** lewat Worker Pipeline untuk
> setiap item `POST /speak` — lihat [Worker Pipeline (Phase 5)](#worker-pipeline-phase-5)
> di bawah. Endpoint `/pause`, `/resume`, `/stop` di atas tetap berguna
> untuk mengontrol playback yang SEDANG berjalan lewat pipeline tsb (mis.
> menghentikan paksa pengumuman yang salah).
>
> Untuk memutar satu file WAV secara manual di luar pipeline (mis. uji
> coba device baru), gunakan script bantu manual (lihat bagian
> "Verifikasi Playback Manual" di bawah).

Contoh `GET /devices` response:
```json
{
  "devices": [
    {"id": 0, "name": "Speaker (Realtek Audio)", "max_output_channels": 2, "default_samplerate": 44100.0, "is_default": true},
    {"id": 3, "name": "Speaker TOA (USB Audio)", "max_output_channels": 2, "default_samplerate": 48000.0, "is_default": false}
  ],
  "count": 2
}
```

Contoh `POST /device`:
```json
{ "device_id": 3 }
```

Response `/pause`, `/resume`, `/stop`, dan `/device` semuanya memakai format yang sama:
```json
{
  "state": "playing",
  "current_file": "cache\\audio\\7f4f14e...wav",
  "selected_device_id": 3
}
```

`state` bernilai salah satu dari: `idle` (tidak ada playback), `playing`, `paused`.

> Jika PortAudio/driver audio tidak terdeteksi di server (mis. dijalankan di mesin tanpa sound card), endpoint `/health`, `/queue`, `/speak` **tetap berfungsi normal** — hanya endpoint di atas yang akan mengembalikan error `502 PLAYBACK_DEVICE_ERROR` yang jelas, bukan membuat seluruh server gagal start (graceful degradation, sama seperti perilaku Piper di Phase 3).

## Verifikasi Playback Manual

Karena Phase 4 belum punya endpoint "play" (lihat catatan di atas), gunakan script bantu berikut untuk benar-benar mendengar hasilnya di Windows:

```powershell
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "$PWD\src"
python scripts\manual_test_playback.py "cache\audio\<nama_file_hasil_tts>.wav"
```

Script ini akan memutar file, menampilkan daftar output device yang terdeteksi, dan menerima perintah `p` (pause) / `r` (resume) / `s` (stop) / `q` (keluar) langsung dari terminal. Ini murni alat bantu verifikasi lokal, bukan bagian dari server/API.

## Worker Pipeline (Phase 5)

Sejak Phase 5, `QueueWorker` (Phase 2, tidak diubah) menjalankan
`AnnouncementPipelineProcessor` sebagai `item_processor`-nya, yang
menyatukan seluruh tahap berikut untuk **setiap** item `POST /speak`
secara otomatis, satu per satu, sesuai priority antrean:

```
Queue → Cache → Generate → Playback → Delay → Queue Berikutnya
```

1. **Queue** — item PENDING di-dequeue (Phase 2).
2. **Cache / Generate** — teks disintesis jadi audio lewat `TTSService`
   (Phase 3): cache hit langsung dipakai, cache miss memanggil Piper.
3. **Playback** — file WAV hasil sintesis diputar ke output device aktif
   (Phase 4), worker menunggu sampai audio **benar-benar selesai
   terdengar** sebelum lanjut.
4. **Delay** — jeda `playback.post_playback_delay_seconds` (default `0.5`
   detik) di `config/config.yaml`, agar antar-pengumuman TOA tidak
   bertabrakan/terlalu rapat. Set `0` untuk menonaktifkan jeda.
5. **Queue Berikutnya** — worker otomatis lanjut ke item PENDING
   berikutnya (priority tertinggi dulu, lalu FIFO).

Pantau progres tiap tahap lewat `GET /queue/{item_id}` atau
`GET /queue?status=...` — `status` item baru menjadi `completed` **setelah
seluruh pipeline** (termasuk playback + delay) selesai, bukan lagi hanya
setelah TTS selesai seperti pada Phase 3.

> **Playback bersifat best-effort, tidak bisa membuat item gagal.** Jika
> sistem audio tidak tersedia (`playback_manager` `None`, lihat catatan
> graceful degradation Phase 4 di atas) atau playback gagal karena alasan
> device/file, tahap Playback dilewati/dicatat sebagai warning di log —
> item tetap `completed` selama tahap TTS-nya sendiri berhasil. Hanya
> kegagalan pada tahap **TTS** (mis. voice tidak ditemukan, Piper belum
> ter-setup) yang membuat item berstatus `failed`, sama seperti Phase 3.

## Endpoint Multi Zone (Phase 6)

Setiap **Zone** adalah jalur audio independen: Queue + Worker + Playback
miliknya sendiri (lihat `src/announcement_server/zones/`). Zone `main`
SELALU ada sejak startup (dibangun dari `queue`/`playback` di
`config.yaml`, opsional di-override lewat `zones.main`) dan **tidak dapat
dihapus** — seluruh endpoint Phase 1-5 (`/speak`, `/queue`, `/clear`,
`/devices`, `/device`, `/pause`, `/resume`, `/stop`) tetap beroperasi di
atas zone ini tanpa perubahan apa pun.

| Method | Path                     | Deskripsi                                                        |
|--------|--------------------------|--------------------------------------------------------------------|
| GET    | `/zones`                 | Melihat daftar seluruh zone + status runtime masing-masing          |
| POST   | `/zones`                 | Membuat zone baru (Queue+Worker+Playback independen)                 |
| PUT    | `/zones/{name}`          | Memperbarui zone (device/volume/enabled) — pembaruan parsial          |
| DELETE | `/zones/{name}`          | Menghapus zone (zone `main` dilindungi, `409`)                          |
| GET    | `/zones/{name}/queue`    | Melihat antrean milik satu zone (sama seperti `GET /queue`)              |
| POST   | `/zones/{name}/device`   | Memilih output device aktif untuk satu zone (sama seperti `POST /device`) |
| POST   | `/zones/{name}/speak`    | *(tambahan, lihat catatan di bawah)* Mengirim pengumuman ke satu zone      |

> ℹ️ **`POST /zones/{name}/speak` — tambahan di luar 6 endpoint literal
> ROADMAP.md Phase 6.** Roadmap hanya mendaftarkan endpoint manajemen
> zone, belum endpoint untuk benar-benar *mengirim* pengumuman ke zone
> tertentu — tanpa endpoint ini, zone yang dibuat tidak akan pernah punya
> isi. Endpoint ini memakai ulang `SpeakRequest`/`QueueItemResponse`
> (Phase 2) apa adanya, tanpa mengubah `api/v1/queue.py` maupun
> `schemas/queue.py` sama sekali. `POST /speak` (Phase 2, tanpa prefix
> zone) **tidak berubah** dan tetap hanya menyasar zone `main`.

Contoh `POST /zones`:

```json
{
  "name": "lobby",
  "device_id": null,
  "volume": 1.0,
  "enabled": true
}
```

Response (`201 Created`):

```json
{
  "name": "lobby",
  "enabled": true,
  "device_id": null,
  "volume": 1.0,
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z",
  "worker_running": true,
  "playback_state": "idle",
  "pending_count": 0,
  "processing_count": 0
}
```

Contoh `PUT /zones/lobby` (pembaruan parsial — hanya field yang dikirim yang berubah):

```json
{ "volume": 0.6, "enabled": false }
```

Contoh mengirim pengumuman ke zone tertentu:

```bash
curl -X POST http://localhost:8000/zones/lobby/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Selamat datang di lobby"}'
```

### Bagaimana Zone volume diterapkan

`volume` pada Zone adalah **gain per-channel** (analog volume knob
amplifier TOA) — **berbeda** dari `volume` pada `POST /speak` (Phase 3,
gain per-item yang sudah dipanggang ke dalam file cache TTS). Zone volume
diterapkan **saat playback**, ke salinan sementara audio (bukan ke file
cache asli — cache TTS berbasis SHA256 di-share oleh seluruh zone), lewat
`AudioProcessor.apply_volume` yang sama persis dipakai Phase 3 (tidak
diduplikasi). Salinan sementara ini dibuat di `cache/zone_audio/{nama_zone}/`
dan otomatis dihapus setelah selesai diputar. Zone `main` memakai gain
`1.0` secara default, sehingga perilakunya identik dengan Phase 5 (file
cache diputar langsung, tanpa salinan sementara).

### Konfigurasi Zone via `config.yaml`

Zone tambahan (selain `main`) juga bisa didefinisikan statis lewat
`config/config.yaml` (dibuat otomatis saat startup) — lihat bagian
`zones:` pada file tersebut. Ini murni kenyamanan; seluruh operasi yang
sama (create/update/delete) tetap bisa dilakukan lewat REST API kapan
saja tanpa restart server.

## Endpoint Scheduler (Phase 8)

Memicu pengumuman otomatis berbasis waktu — mendukung **Daily**,
**Weekly**, dan **One Time** (lihat ROADMAP.md, contoh: 07.00 → Bell,
12.00 → Istirahat, 15.00 → Pulang). Scheduler murni "mengetuk" antrean
yang sudah ada (`QueueManager.enqueue()`, Phase 2/6/7) pada waktu yang
tepat — tidak ada jalur pemrosesan TTS/audio baru.

| Method | Path                        | Deskripsi                                                  |
|--------|-----------------------------|---------------------------------------------------------------|
| GET    | `/scheduler`                | Melihat daftar seluruh jadwal                                  |
| POST   | `/scheduler`                | Membuat jadwal baru                                              |
| GET    | `/scheduler/{id}`           | Melihat detail satu jadwal                                        |
| PUT    | `/scheduler/{id}`           | Memperbarui jadwal (pembaruan parsial)                              |
| DELETE | `/scheduler/{id}`           | Menghapus jadwal                                                     |
| POST   | `/scheduler/{id}/trigger`   | Memicu satu jadwal SEGERA (manual, untuk verifikasi) tanpa memengaruhi jadwal otomatis berikutnya |

Contoh `POST /scheduler` (Daily — Bell Masuk):

```json
{
  "name": "Bell Masuk",
  "zone": "main",
  "recurrence": "daily",
  "time_of_day": "07:00",
  "announcement": { "type": "audio", "file": "bell.wav", "priority": "high" }
}
```

Contoh Weekly (Istirahat, Senin-Jumat):

```json
{
  "name": "Istirahat",
  "recurrence": "weekly",
  "time_of_day": "12:00",
  "days_of_week": [0, 1, 2, 3, 4],
  "announcement": { "type": "tts", "text": "Waktunya istirahat siang." }
}
```

Contoh One Time:

```json
{
  "name": "Pengumuman Khusus",
  "recurrence": "once",
  "time_of_day": "09:00",
  "run_date": "2026-08-17",
  "announcement": { "type": "tts", "text": "Selamat memperingati HUT Kemerdekaan." }
}
```

- `recurrence`: `daily` | `weekly` | `once`.
- `time_of_day`: format `"HH:MM"` atau `"HH:MM:SS"` (24 jam).
- `days_of_week`: **wajib** untuk `weekly` — daftar angka `0` (Senin) s.d. `6` (Minggu). Diabaikan untuk recurrence lain.
- `run_date`: **wajib** untuk `once` — format `"YYYY-MM-DD"`. Ditolak (`422`) jika sudah berlalu.
- `announcement`: sama persis dengan body `POST /speak` (Phase 2/7) — mendukung `type="tts"`/`type="audio"`.
- `zone`: nama zone tujuan (default `"main"`, lihat `GET /zones`).

> ⚠️ Jadwal `once` **otomatis dinonaktifkan** (`enabled: false`, `next_run_at: null`) setelah terpicu satu kali — tidak akan pernah terpicu lagi. Jadwal `daily`/`weekly` otomatis menghitung `next_run_at` berikutnya setiap kali terpicu. Kegagalan saat memicu (mis. zone tujuan sudah dihapus, atau file audio tidak ditemukan) di-log dan TIDAK menghentikan scheduler — `next_run_at` tetap dimajukan untuk mencegah retry rapat.

### Zona waktu & presisi

Scheduler memeriksa jadwal jatuh tempo setiap `scheduler.poll_interval_seconds` (default 5 detik) — cukup presisi untuk jadwal berbasis menit. Default `scheduler.timezone: "local"` memakai jam sistem apa adanya (tanpa tzinfo eksplisit), paling sesuai untuk perangkat PA fisik. Isi dengan nama zona IANA eksplisit (mis. `"Asia/Jakarta"`) jika server dan lokasi pengumuman berada di zona waktu berbeda — pastikan paket `tzdata` terpasang (lihat `requirements.txt`), terutama di Windows.

### Konfigurasi Schedule via `config.yaml`

Jadwal juga bisa didefinisikan statis lewat `config/config.yaml` (bagian
`schedules:`, dibuat otomatis saat startup) — lihat contoh
Bell/Istirahat/Pulang yang sudah disediakan (nonaktif secara default,
sama seperti contoh `zones:`). Jadwal statis maupun yang dibuat lewat API
sama-sama diproses oleh `SchedulerManager` yang sama; tidak ada
perbedaan perilaku.

## Konfigurasi

Konfigurasi utama ada di [`config/config.yaml`](config/config.yaml). Semua
nilai dapat di-override lewat environment variable dengan prefix `APP_` dan
separator nested `__`, contoh:

```bash
APP_SERVER__PORT=9000
APP_LOGGING__LEVEL=DEBUG
```

Bagian `announcement:` (Phase 7) mengatur Announcement Engine:

| Key                                    | Default                       | Deskripsi                                                        |
|-----------------------------------------|--------------------------------|--------------------------------------------------------------------|
| `announcement.sounds_dir`               | `sounds`                       | Direktori file audio statis (bell/alarm/jingle/dst)                 |
| `announcement.ffmpeg_binary_path`       | `ffmpeg`                       | Path executable ffmpeg, atau nama binary jika sudah ada di PATH       |
| `announcement.converted_cache_dir`      | `cache/announcement_audio`     | Cache hasil konversi ffmpeg ke WAV                                    |
| `announcement.conversion_timeout_seconds`| `30.0`                        | Timeout maksimum satu proses konversi ffmpeg                          |

Bagian `scheduler:` (Phase 8) mengatur Scheduler:

| Key                              | Default   | Deskripsi                                                              |
|-----------------------------------|-----------|----------------------------------------------------------------------------|
| `scheduler.poll_interval_seconds` | `5.0`     | Seberapa sering jadwal jatuh tempo diperiksa                                |
| `scheduler.timezone`              | `local`   | `"local"` (jam sistem) atau nama zona IANA eksplisit, mis. `"Asia/Jakarta"`   |

## Menjalankan Test

```bash
pip install -r requirements.txt
export PYTHONPATH=$(pwd)/src
pytest -v
```

Test dibagi beberapa lapisan:
- `tests/test_queue_manager.py`, `test_queue_manager_tts_fields.py` — unit test murni `QueueManager` (priority, FIFO, cancel, clear, full, pruning, field & method TTS), tanpa worker/HTTP.
- `tests/test_queue_worker.py` — integrasi `QueueManager` + `QueueWorker` dengan stub processor (murni Phase 2, tidak diubah).
- `tests/test_queue_api.py` — endpoint HTTP end-to-end, dengan `QueueManager` di-override lewat `app.dependency_overrides` agar deterministik.
- `tests/test_audio_processor.py` — unit test DSP volume/pitch (`AudioProcessor`), pakai WAV sintetis.
- `tests/test_audio_cache.py` — unit test cache SHA256 (`AudioCache`): key deterministik, atomic write, hit/miss.
- `tests/test_engine_factory.py` — unit test registry `EngineFactory` (Open/Closed Principle).
- `tests/test_piper_engine.py` — unit test `PiperEngine` memakai *fake piper executable* (tidak butuh binary Piper asli) untuk memvalidasi plumbing subprocess: sukses, voice tidak ditemukan, binary tidak ada, exit code gagal, timeout.
- `tests/test_tts_service.py` — unit test orkestrasi `TTSService` (cache hit/miss, post-processing) memakai `FakeEngine`.
- `tests/test_queue_tts_integration.py` — test integrasi penuh: `QueueManager` + `QueueWorker` (Phase 2, tidak diubah) + `TTSQueueProcessor` (Phase 3) + `FakeEngine`.
- `tests/test_audio_device_manager.py` — unit test `AudioDeviceManager` memakai fake `sounddevice` module (tidak butuh hardware audio).
- `tests/test_playback_manager.py` — unit test `PlaybackManager`: play, pause/resume (memverifikasi posisi TIDAK reset), stop (idempotent), auto-stop saat audio habis, ganti device, dan `wait_until_finished()` (Phase 5): menunggu selesai alami, selesai karena `stop()`, langsung return saat IDLE.
- `tests/test_playback_api.py` — endpoint HTTP `/devices`, `/device`, `/pause`, `/resume`, `/stop` end-to-end dengan dependency override.
- `tests/test_pipeline_processor.py` — test `AnnouncementPipelineProcessor` (Phase 5): playback dipanggil & ditunggu, playback dilewati saat `PlaybackManager` `None`, kegagalan playback tidak menggagalkan item, kegagalan tahap TTS tetap `failed`, tahap Delay benar-benar menjeda.
- `tests/test_zone_manager.py` — unit test `ZoneManager` (Phase 6): create/list/get/update/delete zone, zone `main` dilindungi dari penghapusan, toggle `enabled` menghentikan/menjalankan worker, tiap zone punya `QueueManager` independen, `shutdown()` menghentikan seluruh zone.
- `tests/test_zones_api.py` — endpoint HTTP `/zones`, `/zones/{name}`, `/zones/{name}/queue`, `/zones/{name}/device`, `/zones/{name}/speak` end-to-end dengan dependency override (`FakeEngine` + `FakeSoundDevice`, tidak butuh Piper/hardware asli); memverifikasi antar-zone (termasuk `main`) benar-benar terisolasi satu sama lain.
- `tests/test_pipeline_processor_volume_gain.py` — test khusus penambahan `volume_gain` (Phase 6) pada `AnnouncementPipelineProcessor`: gain default `1.0` tidak mengubah perilaku Phase 5 sama sekali, gain custom benar-benar men-scale audio yang diputar (dibandingkan lewat `AudioProcessor.apply_volume`) tanpa mengubah file cache asli, gain bisa diubah lewat setter tanpa membuat ulang pipeline, dan kegagalan penerapan gain fallback graceful ke file asli.
- `tests/test_audio_asset_resolver.py` — unit test `AudioAssetResolver` (Phase 7) memakai *fake ffmpeg executable* (pola sama seperti `test_piper_engine.py`, tidak butuh ffmpeg asli): file `.wav` diputar langsung tanpa konversi, file nested di sub-folder `sounds_dir`, file tidak ditemukan, path traversal ditolak, konversi MP3 berhasil + di-cache (panggilan kedua tidak memanggil ffmpeg ulang), ffmpeg tidak ditemukan, ffmpeg gagal (exit code), ffmpeg timeout.
- `tests/test_announcement_source_processor.py` — unit test `AnnouncementSourceProcessor` (Phase 7): item `type=tts` di-dispatch ke `TTSQueueProcessor`, item `type=audio` di-dispatch ke `AudioAssetResolver` dan hasilnya tersimpan lewat `QueueManager.update_tts_result` (bukan ke `TTSQueueProcessor`), item `audio` tanpa `source_file`/dengan file tidak ditemukan melempar error yang sesuai.
- `tests/test_speak_announcement_type_api.py` — dua kelompok test Phase 7: (1) validasi HTTP `POST /speak` untuk `type`/`file` (backward-compat default `type=tts`, `text`/`file` wajib sesuai `type`, `text` otomatis untuk `type=audio` yang tidak diisi); (2) end-to-end `QueueManager` + `AnnouncementSourceProcessor` + `AnnouncementPipelineProcessor` + `QueueWorker` sungguhan (disusun identik dengan `ZoneManager.create_zone`) memverifikasi item `audio` benar-benar selesai/gagal diproses, serta item `tts` dan `audio` tetap bisa diproses berdampingan oleh worker yang sama.
- `tests/test_scheduler_models.py` — unit test murni `compute_next_run`/`parse_time_of_day`/`parse_run_date` (Phase 8): daily (selalu ada next run, boundary tepat di waktu jadwal dianggap sudah lewat), weekly (hari yang sama minggu ini/depan tergantung waktu sudah lewat atau belum, daftar hari kosong → `None`), once (masa depan vs sudah lewat vs `run_date` kosong).
- `tests/test_scheduler_manager.py` — unit test `SchedulerManager` (Phase 8): CRUD jadwal, validasi (`weekly` tanpa `days_of_week`, `once` tanpa/dengan `run_date` sudah lewat, `announcement` tidak konsisten dengan `type`), `trigger_now` (tidak memengaruhi `next_run_at` terjadwal, melempar error untuk zone tujuan yang tidak ada), dan background loop SUNGGUHAN (bukan mock) yang benar-benar memicu jadwal `once` secara otomatis lalu menonaktifkannya.
- `tests/test_scheduler_api.py` — endpoint HTTP `/scheduler` end-to-end dengan dependency override (`FakeEngine`, tidak butuh Piper asli), memverifikasi seluruh skenario create/get/update/delete/trigger beserta validasi 422/404.

## Struktur Project

```
announcement-server/
├── src/announcement_server/
│   ├── main.py                  # Application factory (create_app) + entry point
│   ├── core/
│   │   ├── config.py             # Pydantic v2 settings (YAML + env override): App, Server, Logging, TTS, Playback, Queue, Announcement (Phase 7), Zones (Phase 6), Scheduler (Phase 8, SchedulerConfig + dict[str, ScheduleDefinition])
│   │   ├── logging.py            # Setup logging (rotating file handler)
│   │   └── exceptions.py         # Custom exception hierarchy + global handler (+ Zone* Phase 6, + Audio*/Announcement* Phase 7, + Schedule*/InvalidScheduleError Phase 8)
│   ├── api/
│   │   ├── deps.py               # Dependency Injection providers (Settings, QueueManager, AudioDeviceManager, PlaybackManager, ZoneManager Phase 6, SchedulerManager Phase 8)
│   │   └── v1/
│   │       ├── health.py          # Router: GET /health
│   │       ├── queue.py           # Router: /speak, /queue, /queue/{id}, /clear (+ type=tts|audio sejak Phase 7)
│   │       ├── playback.py        # Router: /devices, /device, /pause, /resume, /stop
│   │       ├── zones.py           # Router (Phase 6): /zones, /zones/{name}, /zones/{name}/queue, /zones/{name}/device, /zones/{name}/speak
│   │       └── scheduler.py       # Router (Phase 8): /scheduler, /scheduler/{id}, /scheduler/{id}/trigger
│   ├── queueing/                 # Domain Queue System (murni, tidak terikat FastAPI)
│   │   ├── models.py              # QueueItem (+ field TTS + AnnouncementType/source_file Phase 7), QueuePriority, QueueItemStatus, DEFAULT_ACTIVE_STATUSES (dipakai bersama queue.py & zones.py)
│   │   ├── manager.py             # QueueManager (asyncio.PriorityQueue + registry; enqueue() + param announcement_type/source_file sejak Phase 7)
│   │   ├── worker.py              # QueueWorker (Phase 2, TIDAK diubah sejak Phase 3/4/5/6/7)
│   │   ├── tts_processor.py       # TTSQueueProcessor — jembatan QueueWorker <-> TTSService (Phase 3), satu instance per zone sejak Phase 6
│   │   └── pipeline_processor.py  # AnnouncementPipelineProcessor — Queue→Cache/Generate→Playback→Delay→Berikutnya (Phase 5) + volume_gain per-zone (Phase 6); Stage 2 diisi AnnouncementSourceProcessor sejak Phase 7 (kontrak ItemProcessor identik, kelas ini TIDAK diubah)
│   ├── announcement/              # Domain Announcement Engine (Phase 7, murni tidak terikat FastAPI/Queue)
│   │   ├── asset_resolver.py      # AudioAssetResolver — validasi & (jika perlu) konversi file audio statis ke WAV lewat ffmpeg, dengan cache hasil konversi
│   │   └── source_processor.py    # AnnouncementSourceProcessor — dispatcher Stage 2 pipeline: TTSQueueProcessor (Phase 3) vs AudioAssetResolver (Phase 7) berdasarkan item.announcement_type
│   ├── tts/                      # Domain TTS Engine (Phase 3, murni tidak terikat FastAPI/Queue; di-share seluruh zone sejak Phase 6)
│   │   ├── engine_base.py         # Interface TTSEngine (Strategy Pattern)
│   │   ├── piper_engine.py        # Implementasi Piper (subprocess async)
│   │   ├── engine_factory.py      # Factory Pattern: nama engine -> instance
│   │   ├── audio_processor.py     # Post-processing volume & pitch (stdlib wave/audioop) — dipakai ulang untuk zone volume gain (Phase 6)
│   │   ├── cache.py               # AudioCache berbasis SHA256 (di-share seluruh zone, TIDAK per-zone)
│   │   ├── service.py             # TTSService: orkestrator cache -> engine -> post-processing
│   │   └── models.py              # TTSResult
│   ├── playback/                 # Domain Audio Playback (Phase 4; dipakai lewat pipeline sejak Phase 5; satu instance per zone sejak Phase 6)
│   │   ├── models.py              # AudioDevice, PlaybackState
│   │   ├── device_manager.py      # AudioDeviceManager (enumerasi & validasi output device, di-share seluruh zone)
│   │   └── manager.py             # PlaybackManager (callback-based stream: play/pause/resume/stop/wait_until_finished)
│   ├── zones/                    # Domain Multi Zone (Phase 6, murni tidak terikat FastAPI)
│   │   ├── models.py              # Zone (metadata: name/enabled/device_id/volume/timestamps), MAIN_ZONE_NAME
│   │   └── manager.py             # ZoneManager — orkestrasi create/update/delete/lookup zone, membungkus QueueManager+QueueWorker+PlaybackManager+AnnouncementSourceProcessor(Phase 7)+Pipeline per zone
│   ├── scheduler/                 # Domain Scheduler (Phase 8, murni tidak terikat FastAPI)
│   │   ├── models.py              # ScheduleRecurrence, AnnouncementSpec, ScheduleEntry, compute_next_run (fungsi murni), parse_time_of_day/parse_run_date
│   │   └── manager.py             # SchedulerManager — registry jadwal (CRUD, pola sama ZoneManager) + background loop yang meng-enqueue lewat QueueManager.enqueue() milik zone tujuan (tidak diduplikasi)
│   └── schemas/
│       ├── health.py              # Response schema /health
│       ├── queue.py                # Request/response schema Queue + TTS + type/file (Phase 7)
│       ├── playback.py             # Request/response schema Playback
│       ├── zones.py                # Request/response schema Zone (Phase 6) — reuse schema queue.py/playback.py untuk sub-endpoint queue/device/speak
│       └── scheduler.py            # Request/response schema Scheduler (Phase 8) — reuse SpeakRequest (queue.py) untuk field `announcement`
├── config/config.yaml
├── engines/piper/                # (dibuat manual) binary + model Piper — lihat "Setup Piper" di atas
├── sounds/                       # (dibuat manual, Phase 7) file audio statis (bell/alarm/jingle/dst) — lihat announcement.sounds_dir
├── cache/audio/                  # (dibuat otomatis) cache audio hasil TTS, di-share seluruh zone
├── cache/zone_audio/{nama_zone}/ # (dibuat otomatis) salinan audio sementara ber-gain zone (Phase 6), auto-dihapus setelah diputar
├── cache/announcement_audio/     # (dibuat otomatis, Phase 7) cache hasil konversi ffmpeg (file non-WAV -> WAV) untuk item type=audio
├── scripts/
│   └── manual_test_playback.py   # Alat bantu verifikasi playback manual (bukan bagian API)
├── logs/
├── tests/
├── requirements.txt
├── pytest.ini
├── run.bat
└── README.md
```

## Roadmap

Lihat dokumen roadmap lengkap (`Text To Speech Announcement Server Roadmap`)
untuk daftar 15 fase pengembangan, dari Project Foundation hingga Future
Development (multi-engine TTS, Audio over IP, dashboard web, dsb).
