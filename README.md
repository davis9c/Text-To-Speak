# Announcement Server

Production Ready Text-to-Speech Announcement Server berbasis Python untuk Windows.
Menerima request HTTP, mengantrekan pengumuman, mengubah teks menjadi suara
(offline), memutar audio ke sistem TOA, serta mendukung Public Address (PA)
multi-zona.

> **Status:** Phase 6 — Multi Zone. Server kini mendukung banyak "jalur audio" independen (Zone): tiap Zone punya Queue, Worker, dan Playback miliknya sendiri, dapat dikelola lewat REST API (`/zones`) tanpa restart server. Zone `main` (Phase 1-5) tetap ada otomatis dan seluruh endpoint lama (`/speak`, `/queue`, `/devices`, dst) tidak berubah sama sekali. Lihat [Endpoint Multi Zone (Phase 6)](#endpoint-multi-zone-phase-6) di bawah.

## Requirements

- Python 3.11+
- Windows 10/11 (development/production) — kompatibel juga di Linux/macOS untuk development.
- **Piper TTS** (untuk fitur Text-to-Speech, Phase 3 ke atas) — lihat bagian [Setup Piper (TTS Engine)](#setup-piper-tts-engine) di bawah.

## Setup Piper (TTS Engine)

Server ini memakai [Piper](https://github.com/rhasspy/piper) sebagai engine TTS offline default. Piper **tidak disertakan** dalam repository ini (ukurannya besar & berlisensi terpisah) — unduh secara manual:

1. Unduh binary Piper untuk Windows dari [rilis resmi Piper](https://github.com/rhasspy/piper/releases) (pilih `piper_windows_amd64.zip` atau setara).
2. Ekstrak sehingga `piper.exe` berada di `engines/piper/piper.exe` (relatif terhadap root project), atau sesuaikan path lewat `tts.piper_binary_path` di `config/config.yaml`.
3. Unduh minimal satu voice model (mis. `en_US-lessac-medium`) dari [halaman voices Piper](https://github.com/rhasspy/piper/blob/master/VOICES.md) — setiap voice terdiri dari 2 file: `<voice>.onnx` dan `<voice>.onnx.json`.
4. Taruh keduanya di `engines/piper/models/`, atau sesuaikan lewat `tts.piper_models_dir`.
5. Set `tts.default_voice` di `config/config.yaml` sesuai nama voice yang diunduh (tanpa ekstensi).

> Jika Piper belum ter-setup, server tetap bisa berjalan normal (endpoint `/health`, `/queue`, dll tetap berfungsi) — hanya item yang dikirim lewat `POST /speak` yang akan berstatus `failed` saat diproses, dengan `error_message` yang menjelaskan penyebabnya. Ini disengaja (graceful degradation) agar satu komponen yang belum siap tidak menjatuhkan seluruh server.

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

## Endpoint Queue System (Phase 2) + TTS (Phase 3)

| Method | Path              | Deskripsi                                            |
|--------|-------------------|-------------------------------------------------------|
| POST   | `/speak`          | Menambahkan pengumuman baru ke antrean (+ parameter TTS) |
| GET    | `/queue`          | Melihat antrean (default: item aktif — pending/processing) |
| DELETE | `/queue/{item_id}`| Membatalkan item PENDING                              |
| POST   | `/clear`          | Membatalkan seluruh item PENDING                       |

Contoh `POST /speak`:

```json
{
  "text": "Nomor antrean A001, silakan menuju loket 3.",
  "priority": "normal",
  "voice": null,
  "speed": 1.0,
  "pitch": 1.0,
  "volume": 1.0
}
```

- `priority`: `urgent` | `high` | `normal` (default) | `low`.
- `voice`: nama voice Piper (mis. `en_US-lessac-medium`). Kosongkan (`null`) untuk memakai `tts.default_voice` dari config.
- `speed`: 0.5–2.0 (1.0 = normal). Dipetakan ke parameter native Piper `--length_scale`.
- `pitch`: 0.5–2.0 (1.0 = normal). **Catatan:** memakai teknik resampling sederhana yang turut memengaruhi tempo/durasi audio (lihat docstring `AudioProcessor.apply_pitch` untuk detail keterbatasan).
- `volume`: 0.0–2.0 (1.0 = normal).

Response (`201 Created`) — sama seperti Phase 2, ditambah field TTS:

```json
{
  "id": "a1b2c3d4-...",
  "text": "Nomor antrean A001, silakan menuju loket 3.",
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

> ⚠️ **Penting — seluruh pipeline (TTS + Playback) terjadi ASINKRON.** Response `201` di atas hanya berarti item berhasil masuk antrean, BUKAN berarti audio sudah jadi/diputar (`audio_file_path` masih `null`). QueueWorker memproses item di background lewat Worker Pipeline (Phase 5); pantau progres lewat `GET /queue?status=completed` (audio sudah jadi DAN — jika sistem audio tersedia — sudah selesai diputar, `audio_file_path` terisi) atau `GET /queue?status=failed` (lihat `error_message`, mis. voice tidak ditemukan atau Piper belum ter-setup — kegagalan playback TIDAK membuat item `failed`, lihat [Worker Pipeline (Phase 5)](#worker-pipeline-phase-5)).
>
> Audio yang dihasilkan disimpan sebagai file `.wav` di `tts.cache_dir` (default `cache/audio/`), dengan nama file = SHA256 dari kombinasi `engine + voice + text + speed + pitch + volume`. Mengirim teks yang sama persis dengan parameter sama akan langsung memakai cache (`cache_hit: true`) tanpa memanggil Piper ulang.
>
> Audio tidak diputar sama sekali dalam pemrosesan Phase 3. Sejak **Phase 5**, audio hasil sintesis ini **otomatis diputar** ke output device aktif oleh Worker Pipeline setelah tahap TTS selesai — lihat [Worker Pipeline (Phase 5)](#worker-pipeline-phase-5).

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

## Konfigurasi

Konfigurasi utama ada di [`config/config.yaml`](config/config.yaml). Semua
nilai dapat di-override lewat environment variable dengan prefix `APP_` dan
separator nested `__`, contoh:

```bash
APP_SERVER__PORT=9000
APP_LOGGING__LEVEL=DEBUG
```

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

## Struktur Project

```
announcement-server/
├── src/announcement_server/
│   ├── main.py                  # Application factory (create_app) + entry point
│   ├── core/
│   │   ├── config.py             # Pydantic v2 settings (YAML + env override): App, Server, Logging, TTS, Playback, Queue, Zones (Phase 6, dict[str, ZoneDefinition])
│   │   ├── logging.py            # Setup logging (rotating file handler)
│   │   └── exceptions.py         # Custom exception hierarchy + global handler (+ Zone* exceptions Phase 6)
│   ├── api/
│   │   ├── deps.py               # Dependency Injection providers (Settings, QueueManager, AudioDeviceManager, PlaybackManager, ZoneManager Phase 6)
│   │   └── v1/
│   │       ├── health.py          # Router: GET /health
│   │       ├── queue.py           # Router: /speak, /queue, /queue/{id}, /clear
│   │       ├── playback.py        # Router: /devices, /device, /pause, /resume, /stop
│   │       └── zones.py           # Router (Phase 6): /zones, /zones/{name}, /zones/{name}/queue, /zones/{name}/device, /zones/{name}/speak
│   ├── queueing/                 # Domain Queue System (murni, tidak terikat FastAPI)
│   │   ├── models.py              # QueueItem (+ field TTS), QueuePriority, QueueItemStatus, DEFAULT_ACTIVE_STATUSES (dipakai bersama queue.py & zones.py)
│   │   ├── manager.py             # QueueManager (asyncio.PriorityQueue + registry)
│   │   ├── worker.py              # QueueWorker (Phase 2, TIDAK diubah sejak Phase 3/4/5/6)
│   │   ├── tts_processor.py       # TTSQueueProcessor — jembatan QueueWorker <-> TTSService (Phase 3), satu instance per zone sejak Phase 6
│   │   └── pipeline_processor.py  # AnnouncementPipelineProcessor — Queue→Cache→Generate→Playback→Delay→Berikutnya (Phase 5) + volume_gain per-zone (Phase 6)
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
│   │   └── manager.py             # ZoneManager — orkestrasi create/update/delete/lookup zone, membungkus QueueManager+QueueWorker+PlaybackManager+Pipeline per zone
│   └── schemas/
│       ├── health.py              # Response schema /health
│       ├── queue.py                # Request/response schema Queue + TTS
│       ├── playback.py             # Request/response schema Playback
│       └── zones.py                # Request/response schema Zone (Phase 6) — reuse schema queue.py/playback.py untuk sub-endpoint queue/device
├── config/config.yaml
├── engines/piper/                # (dibuat manual) binary + model Piper — lihat "Setup Piper" di atas
├── cache/audio/                  # (dibuat otomatis) cache audio hasil TTS, di-share seluruh zone
├── cache/zone_audio/{nama_zone}/ # (dibuat otomatis) salinan audio sementara ber-gain zone (Phase 6), auto-dihapus setelah diputar
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
