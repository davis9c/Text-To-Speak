# Announcement Server

Production Ready Text-to-Speech Announcement Server berbasis Python untuk Windows.
Menerima request HTTP, mengantrekan pengumuman, mengubah teks menjadi suara
(offline), memutar audio ke sistem TOA, serta mendukung Public Address (PA)
multi-zona.

> **Status:** Phase 2 — Queue System (request masuk antrean; TTS & audio playback nyata belum ada, menyusul Phase 3-4).

## Requirements

- Python 3.11+
- Windows 10/11 (development/production) — kompatibel juga di Linux/macOS untuk development.

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

## Endpoint Queue System (Phase 2)

| Method | Path              | Deskripsi                                            |
|--------|-------------------|-------------------------------------------------------|
| POST   | `/speak`          | Menambahkan pengumuman baru ke antrean                |
| GET    | `/queue`          | Melihat antrean (default: item aktif — pending/processing) |
| DELETE | `/queue/{item_id}`| Membatalkan item PENDING                              |
| POST   | `/clear`          | Membatalkan seluruh item PENDING                       |

Contoh `POST /speak`:

```json
{
  "text": "Nomor antrean A001, silakan menuju loket 3.",
  "priority": "normal"
}
```

`priority` menerima salah satu dari: `urgent`, `high`, `normal` (default), `low`.

Response (`201 Created`):

```json
{
  "id": "a1b2c3d4-...",
  "text": "Nomor antrean A001, silakan menuju loket 3.",
  "priority": "normal",
  "status": "pending",
  "created_at": "2026-07-22T10:00:00Z",
  "updated_at": "2026-07-22T10:00:00Z",
  "error_message": null,
  "position": 1
}
```

> ⚠️ Pada Phase 2 belum ada TTS/audio nyata. Worker hanya memindahkan
> status item dari `pending` → `processing` → `completed` sebagai
> placeholder, memakai processor "stub" yang akan digantikan pipeline
> TTS + Playback pada Phase 5.

`GET /queue` mendukung query param opsional `status` untuk melihat status
tertentu, termasuk riwayat (`completed`, `failed`, `cancelled`) selama
masih tersimpan di memory (dibatasi `queue.max_history` pada config).

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

Test dibagi 3 lapisan:
- `tests/test_queue_manager.py` — unit test murni `QueueManager` (priority order, FIFO, cancel, clear, full, pruning), tanpa worker/HTTP.
- `tests/test_queue_worker.py` — integrasi `QueueManager` + `QueueWorker` (memastikan status benar-benar berpindah pending → processing → completed/failed, item cancelled dilewati).
- `tests/test_queue_api.py` — endpoint HTTP end-to-end, dengan `QueueManager` di-override lewat `app.dependency_overrides` agar deterministik (tidak diproses otomatis oleh worker aplikasi).

## Struktur Project

```
announcement-server/
├── src/announcement_server/
│   ├── main.py                  # Application factory (create_app) + entry point
│   ├── core/
│   │   ├── config.py             # Pydantic v2 settings (YAML + env override, termasuk QueueConfig)
│   │   ├── logging.py            # Setup logging (rotating file handler)
│   │   └── exceptions.py         # Custom exception hierarchy + global handler
│   ├── api/
│   │   ├── deps.py               # Dependency Injection providers (Settings, QueueManager)
│   │   └── v1/
│   │       ├── health.py          # Router: GET /health
│   │       └── queue.py           # Router: /speak, /queue, /queue/{id}, /clear
│   ├── queueing/                 # Domain Queue System (murni, tidak terikat FastAPI)
│   │   ├── models.py              # QueueItem, QueuePriority, QueueItemStatus
│   │   ├── manager.py             # QueueManager (asyncio.PriorityQueue + registry)
│   │   └── worker.py              # QueueWorker (background task konsumen antrean)
│   └── schemas/
│       ├── health.py              # Response schema /health
│       └── queue.py                # Request/response schema Queue System
├── config/config.yaml
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
