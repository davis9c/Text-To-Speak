"""Application entry point.

Menggunakan pola *application factory* (``create_app``) agar:
- Mudah dites (setiap test bisa membuat instance app baru dengan
  settings/override berbeda, tanpa saling mempengaruhi).
- Mudah dikembangkan (menambah router/middleware baru di fase berikutnya
  cukup mendaftarkannya di sini, tidak menyebar di banyak tempat).
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from announcement_server import __version__
from announcement_server.api.v1.health import router as health_router
from announcement_server.api.v1.playback import router as playback_router
from announcement_server.api.v1.queue import router as queue_router
from announcement_server.api.v1.zones import router as zones_router
from announcement_server.core.config import AppSettings, get_settings
from announcement_server.core.exceptions import register_exception_handlers
from announcement_server.core.logging import setup_logging
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.tts.service import TTSService
from announcement_server.zones.manager import ZoneManager
from announcement_server.zones.models import MAIN_ZONE_NAME

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup & shutdown hook.

    Menginisialisasi resource jangka panjang (Queue System pada Phase 2,
    TTS Engine pada Phase 3, dst) dan memastikannya berhenti secara
    graceful saat shutdown.
    """
    settings: AppSettings = app.state.settings
    logger.info(
        "Starting %s v%s (environment=%s)",
        settings.app.name,
        __version__,
        settings.app.environment,
    )

    # Audio Device (Phase 4): di-share oleh SELURUH zone (Phase 6) karena
    # enumerasi device bersifat stateless terhadap zone mana pun. Inisialisasi
    # tetap dibuat graceful seperti sejak Phase 4: jika PortAudio/driver audio
    # tidak terdeteksi (mis. server tanpa sound card, atau driver belum
    # terinstall), server TETAP bisa start dan endpoint lain (health, queue,
    # speak) tetap berfungsi normal — hanya endpoint Playback yang akan
    # mengembalikan error jelas saat dipanggil (lihat api/deps.py), dan
    # tahap Playback pada pipeline tiap zone akan dilewati (lihat
    # queueing/pipeline_processor.py) — bukan membuat seluruh server gagal
    # start ataupun menggagalkan item antrean.
    audio_device_manager: AudioDeviceManager | None
    try:
        audio_device_manager = AudioDeviceManager()
    except Exception:
        logger.warning(
            "Sistem audio (PortAudio/driver) tidak tersedia di mesin ini. Endpoint "
            "/devices, /device, /pause, /resume, /stop (di setiap zone) akan mengembalikan "
            "error hingga driver audio terdeteksi, dan tahap Playback pada pipeline Worker "
            "akan dilewati.",
            exc_info=True,
        )
        audio_device_manager = None
    app.state.audio_device_manager = audio_device_manager

    # TTS Engine (Phase 3): TTSService dibangun sekali (membuat instance
    # engine + cache) dan di-share oleh SELURUH zone (Phase 6) — engine TTS
    # & cache audio berbasis SHA256 independen dari konsep zone, sehingga
    # menggandakannya per zone hanya akan memboroskan resource.
    tts_service = TTSService(settings.tts)
    app.state.tts_service = tts_service

    # Multi Zone (Phase 6): ZoneManager mengorkestrasi Queue + Worker +
    # Playback + Pipeline (Phase 2/4/5, tidak diduplikasi) untuk setiap
    # zone. Zone "main" SELALU dibuat dari config 'queue'/'playback' di
    # atas (opsional di-override oleh `zones.main` di config.yaml jika ada)
    # — persis perilaku satu-satunya jalur audio yang ada sejak Phase 1-5,
    # sehingga endpoint /speak, /queue, /clear, /devices, /device, /pause,
    # /resume, /stop TIDAK BERUBAH SAMA SEKALI dan tetap beroperasi di atas
    # zone ini lewat alias `app.state.queue_manager`/`playback_manager` di
    # bawah (full backward compatibility).
    zone_manager = ZoneManager(
        audio_device_manager=audio_device_manager,
        tts_service=tts_service,
        default_max_size=settings.queue.max_size,
        default_max_history=settings.queue.max_history,
        default_post_playback_delay_seconds=settings.playback.post_playback_delay_seconds,
    )
    app.state.zone_manager = zone_manager

    main_zone_config = settings.zones.get(MAIN_ZONE_NAME)
    await zone_manager.create_zone(
        MAIN_ZONE_NAME,
        device_id=main_zone_config.device_id if main_zone_config else settings.playback.default_device_id,
        volume=main_zone_config.volume if main_zone_config else 1.0,
        enabled=main_zone_config.enabled if main_zone_config else True,
    )
    for zone_name, zone_config in settings.zones.items():
        if zone_name == MAIN_ZONE_NAME:
            continue
        await zone_manager.create_zone(
            zone_name,
            device_id=zone_config.device_id,
            volume=zone_config.volume,
            enabled=zone_config.enabled,
        )

    # Alias backward-compat (Phase 1-5): endpoint & dependency yang sudah
    # ada (api/deps.py) TIDAK diubah sama sekali dan tetap membaca
    # app.state.queue_manager / app.state.playback_manager / app.state.queue_worker
    # apa adanya — nilainya sekarang diambil dari zone "main" milik ZoneManager.
    app.state.queue_manager = zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    app.state.playback_manager = zone_manager.get_playback_manager(MAIN_ZONE_NAME)
    app.state.queue_worker = zone_manager.get_queue_worker(MAIN_ZONE_NAME)

    yield

    await zone_manager.shutdown()
    logger.info("Shutting down %s", settings.app.name)


def create_app(config_path: str | None = None) -> FastAPI:
    """Application factory.

    Args:
        config_path: Path opsional ke file config YAML. Berguna untuk
            testing (mis. memakai config/test.yaml).
    """
    settings = get_settings(config_path)
    setup_logging(settings.logging)

    app = FastAPI(
        title=settings.app.name,
        description=settings.app.description,
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def add_request_id_and_timing(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Menambahkan request_id unik & mencatat durasi setiap request.

        request_id disisipkan ke response header dan dipakai juga oleh
        exception handler agar error mudah ditelusuri di log (traceability),
        penting untuk sistem yang berjalan 24/7 tanpa pengawasan langsung.
        """
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start_time = time.perf_counter()

        response: JSONResponse = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        logger.debug(
            "%s %s -> %s (%.2fms) [request_id=%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(queue_router)
    app.include_router(playback_router)
    app.include_router(zones_router)

    return app


# Instance default yang dipakai oleh Uvicorn (mis. `uvicorn announcement_server.main:app`).
app = create_app()
