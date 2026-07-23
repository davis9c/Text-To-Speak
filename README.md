# Announcement Server

Production Ready Text-to-Speech Announcement Server berbasis Python untuk Windows.
Menerima request HTTP, mengantrekan pengumuman, mengubah teks menjadi suara
(offline), memutar audio ke sistem TOA, serta mendukung Public Address (PA)
multi-zona.

> **Status:** Phase 1 — Project Foundation (belum ada fitur TTS/Queue/Audio).

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

## Struktur Project

```
announcement-server/
├── src/announcement_server/
│   ├── main.py                # Application factory (create_app) + entry point
│   ├── core/
│   │   ├── config.py           # Pydantic v2 settings (YAML + env override)
│   │   ├── logging.py          # Setup logging (rotating file handler)
│   │   └── exceptions.py       # Custom exception hierarchy + global handler
│   ├── api/
│   │   ├── deps.py             # Dependency Injection providers
│   │   └── v1/health.py        # Router: GET /health
│   └── schemas/health.py       # Pydantic response schema
├── config/config.yaml
├── logs/
├── tests/
├── requirements.txt
├── run.bat
└── README.md
```

## Roadmap

Lihat dokumen roadmap lengkap (`Text To Speech Announcement Server Roadmap`)
untuk daftar 15 fase pengembangan, dari Project Foundation hingga Future
Development (multi-engine TTS, Audio over IP, dashboard web, dsb).
