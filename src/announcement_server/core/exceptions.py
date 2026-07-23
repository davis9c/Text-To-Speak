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
