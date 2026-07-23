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
from announcement_server.api.v1.queue import router as queue_router
from announcement_server.core.config import AppSettings, get_settings
from announcement_server.core.exceptions import register_exception_handlers
from announcement_server.core.logging import setup_logging
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.worker import QueueWorker

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

    # Queue System (Phase 2): QueueManager & QueueWorker dibuat SEKALI di
    # sini (bukan per-request) karena keduanya menyimpan state jangka
    # panjang (antrean, registry item) yang harus hidup selama proses
    # server berjalan. Worker mulai berjalan sebagai background task saat
    # startup dan dihentikan secara graceful saat shutdown, agar item yang
    # sedang PROCESSING tidak terpotong paksa.
    queue_manager = QueueManager(max_size=settings.queue.max_size, max_history=settings.queue.max_history)
    app.state.queue_manager = queue_manager

    queue_worker = QueueWorker(queue_manager)
    queue_worker.start()
    app.state.queue_worker = queue_worker

    yield

    await queue_worker.stop()
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

    return app


# Instance default yang dipakai oleh Uvicorn (mis. `uvicorn announcement_server.main:app`).
app = create_app()
