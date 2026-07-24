"""Custom exception hierarchy & global exception handler.

Semua exception domain aplikasi (Queue penuh, TTS engine gagal, Device audio
tidak ditemukan, dsb pada fase-fase berikutnya) sebaiknya diturunkan dari
``AppError`` supaya penanganan error di layer HTTP konsisten dan terpusat,
dan tidak membocorkan stack trace internal ke client (penting untuk sistem
production 24/7).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class untuk seluruh domain exception aplikasi.

    Attributes:
        message: Pesan error yang aman ditampilkan ke client.
        status_code: HTTP status code yang sesuai.
        error_code: Kode error singkat, stabil, dapat dipakai client/monitoring
            (mis. "QUEUE_FULL", "TTS_ENGINE_UNAVAILABLE").
        details: Informasi tambahan opsional (mis. field mana yang invalid).
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AppError):
    """Kesalahan konfigurasi aplikasi (mis. YAML invalid)."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "CONFIGURATION_ERROR"


class NotFoundError(AppError):
    """Resource yang diminta tidak ditemukan."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class ValidationAppError(AppError):
    """Kesalahan validasi domain (di luar validasi request body oleh Pydantic)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"


class ConflictError(AppError):
    """Base class untuk konflik state (aksi tidak valid pada state resource saat ini)."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"


# --- Queue System (Phase 2) -------------------------------------------------


class QueueFullError(ConflictError):
    """Antrean sudah mencapai kapasitas maksimum (item PENDING)."""

    error_code = "QUEUE_FULL"


class QueueItemNotFoundError(NotFoundError):
    """Item antrean dengan id tertentu tidak ditemukan di registry."""

    error_code = "QUEUE_ITEM_NOT_FOUND"


class QueueItemNotCancellableError(ConflictError):
    """Item antrean tidak dapat dibatalkan karena statusnya bukan PENDING."""

    error_code = "QUEUE_ITEM_NOT_CANCELLABLE"


# --- TTS Engine (Phase 3) ----------------------------------------------------
#
# Exception di bawah ini umumnya TIDAK menyentuh HTTP layer secara langsung.
# Sintesis TTS terjadi secara asinkron di dalam QueueWorker (bukan di dalam
# request POST /speak), sehingga saat exception ini terjadi, ia ditangkap
# oleh QueueWorker (lihat queueing/worker.py, sudah ada sejak Phase 2) dan
# diterjemahkan menjadi status item = FAILED + error_message. Client
# mengetahui kegagalan lewat GET /queue?status=failed, bukan lewat response
# error HTTP langsung. Class-nya tetap diturunkan dari AppError (bukan
# Exception biasa) demi konsistensi hierarki dan supaya tetap bisa dipakai
# lewat jalur HTTP biasa jika kelak ada endpoint sinkron (mis. "test voice").


class TTSEngineNotAvailableError(AppError):
    """Engine TTS tidak tersedia (nama engine tidak terdaftar, atau binary/dependency tidak ditemukan)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "TTS_ENGINE_NOT_AVAILABLE"


class TTSGenerationError(AppError):
    """Proses sintesis TTS gagal (exit code non-zero, timeout, output tidak valid, dsb)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "TTS_GENERATION_FAILED"


class VoiceNotFoundError(NotFoundError):
    """Voice/model yang diminta tidak ditemukan pada direktori model engine."""

    error_code = "VOICE_NOT_FOUND"


# --- Audio Playback (Phase 4) ------------------------------------------------


class AudioDeviceNotFoundError(NotFoundError):
    """Device output audio dengan id tertentu tidak ditemukan pada sistem."""

    error_code = "AUDIO_DEVICE_NOT_FOUND"


class AudioFileNotFoundError(NotFoundError):
    """File audio yang akan diputar tidak ditemukan di disk."""

    error_code = "AUDIO_FILE_NOT_FOUND"


class PlaybackStateError(ConflictError):
    """Aksi playback (pause/resume) tidak valid untuk state saat ini."""

    error_code = "PLAYBACK_STATE_ERROR"


class PlaybackDeviceError(AppError):
    """PortAudio/driver gagal membuka atau menulis ke output device."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "PLAYBACK_DEVICE_ERROR"


# --- Multi Zone (Phase 6) -----------------------------------------------------
#
# Setiap Zone (lihat ``zones/manager.py``) membungkus QueueManager + QueueWorker
# + PlaybackManager miliknya sendiri. Exception di bawah ini murni soal
# *manajemen* zone (CRUD, proteksi zone "main") — TIDAK menggantikan exception
# Queue System (Phase 2) maupun Playback (Phase 4) yang tetap dipakai apa
# adanya oleh setiap zone untuk error di dalam queue/playback milik zone itu.


class ZoneNotFoundError(NotFoundError):
    """Zone dengan nama tertentu tidak terdaftar di ZoneManager."""

    error_code = "ZONE_NOT_FOUND"


class ZoneAlreadyExistsError(ConflictError):
    """Nama zone yang diminta sudah dipakai oleh zone lain."""

    error_code = "ZONE_ALREADY_EXISTS"


class ZoneProtectedError(ConflictError):
    """Operasi tidak diizinkan pada zone yang dilindungi (mis. menghapus zone 'main').

    Zone ``main`` WAJIB selalu ada karena seluruh endpoint Phase 1-5
    (``/speak``, ``/queue``, ``/devices``, ``/device``, ``/pause``, dst)
    beroperasi di atasnya demi backward compatibility.
    """

    error_code = "ZONE_PROTECTED"


class ZoneDisabledError(ConflictError):
    """Zone ditemukan tetapi sedang nonaktif (enabled=false) sehingga tidak dapat menerima pengumuman baru."""

    error_code = "ZONE_DISABLED"


def _error_response(request_id: str, error_code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": False,
        "error": {
            "code": error_code,
            "message": message,
            "details": details,
        },
        "request_id": request_id,
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Mendaftarkan seluruh global exception handler ke FastAPI app.

    Dipanggil sekali saat app startup (lihat ``main.py``).
    """

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.warning(
            "AppError ditangani: %s (code=%s, path=%s, request_id=%s)",
            exc.message,
            exc.error_code,
            request.url.path,
            request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_response(request_id, exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.info("Request validation error pada path=%s: %s", request.url.path, exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_response(
                request_id,
                "REQUEST_VALIDATION_ERROR",
                "Request tidak valid.",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.exception(
            "Unhandled exception pada path=%s (request_id=%s): %s",
            request.url.path,
            request_id,
            exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_response(
                request_id,
                "INTERNAL_ERROR",
                "Terjadi kesalahan internal pada server.",
                {},
            ),
        )
