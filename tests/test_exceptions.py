"""Unit test untuk core/exceptions.py (Phase 13 — coverage gap-fill).

Memakai FastAPI app minimal (bukan `create_app()` penuh) supaya
``register_exception_handlers`` diuji terisolasi dari seluruh wiring
lifespan/router aplikasi.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from announcement_server.core.exceptions import (
    AppError,
    AudioAssetNotFoundError,
    AudioConversionError,
    AudioConversionUnavailableError,
    AudioDeviceNotFoundError,
    AudioFileNotFoundError,
    ConfigurationError,
    ConflictError,
    InvalidScheduleError,
    NotFoundError,
    PlaybackDeviceError,
    PlaybackStateError,
    QueueFullError,
    QueueItemNotCancellableError,
    QueueItemNotFoundError,
    ScheduleNotFoundError,
    TTSEngineNotAvailableError,
    TTSGenerationError,
    ValidationAppError,
    VoiceNotFoundError,
    ZoneAlreadyExistsError,
    ZoneDisabledError,
    ZoneNotFoundError,
    ZoneProtectedError,
    register_exception_handlers,
)


# --- AppError dasar -----------------------------------------------------


def test_app_error_stores_message_and_defaults_details() -> None:
    error = AppError("pesan error")
    assert error.message == "pesan error"
    assert error.details == {}
    assert str(error) == "pesan error"


def test_app_error_stores_custom_details() -> None:
    error = AppError("pesan", details={"field": "value"})
    assert error.details == {"field": "value"}


def test_app_error_default_status_and_code() -> None:
    error = AppError("x")
    assert error.status_code == 500
    assert error.error_code == "INTERNAL_ERROR"


@pytest.mark.parametrize(
    "exc_class,expected_status,expected_code",
    [
        (ConfigurationError, 500, "CONFIGURATION_ERROR"),
        (NotFoundError, 404, "NOT_FOUND"),
        (ValidationAppError, 422, "VALIDATION_ERROR"),
        (ConflictError, 409, "CONFLICT"),
        (QueueFullError, 409, "QUEUE_FULL"),
        (QueueItemNotFoundError, 404, "QUEUE_ITEM_NOT_FOUND"),
        (QueueItemNotCancellableError, 409, "QUEUE_ITEM_NOT_CANCELLABLE"),
        (TTSEngineNotAvailableError, 503, "TTS_ENGINE_NOT_AVAILABLE"),
        (TTSGenerationError, 502, "TTS_GENERATION_FAILED"),
        (VoiceNotFoundError, 404, "VOICE_NOT_FOUND"),
        (AudioDeviceNotFoundError, 404, "AUDIO_DEVICE_NOT_FOUND"),
        (AudioFileNotFoundError, 404, "AUDIO_FILE_NOT_FOUND"),
        (PlaybackStateError, 409, "PLAYBACK_STATE_ERROR"),
        (PlaybackDeviceError, 502, "PLAYBACK_DEVICE_ERROR"),
        (ZoneNotFoundError, 404, "ZONE_NOT_FOUND"),
        (ZoneAlreadyExistsError, 409, "ZONE_ALREADY_EXISTS"),
        (ZoneProtectedError, 409, "ZONE_PROTECTED"),
        (ZoneDisabledError, 409, "ZONE_DISABLED"),
        (AudioAssetNotFoundError, 404, "AUDIO_ASSET_NOT_FOUND"),
        (AudioConversionUnavailableError, 503, "AUDIO_CONVERSION_UNAVAILABLE"),
        (AudioConversionError, 502, "AUDIO_CONVERSION_FAILED"),
        (ScheduleNotFoundError, 404, "SCHEDULE_NOT_FOUND"),
        (InvalidScheduleError, 422, "INVALID_SCHEDULE"),
    ],
)
def test_exception_status_and_error_code(exc_class: type[AppError], expected_status: int, expected_code: str) -> None:
    error = exc_class("pesan uji")
    assert error.status_code == expected_status
    assert error.error_code == expected_code
    assert isinstance(error, AppError)


# --- register_exception_handlers (app minimal) -----------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/raise-app-error")
    async def raise_app_error():  # type: ignore[no-untyped-def]
        raise ZoneNotFoundError("Zone 'x' tidak ditemukan.", details={"name": "x"})

    @test_app.get("/raise-unexpected")
    async def raise_unexpected():  # type: ignore[no-untyped-def]
        raise RuntimeError("kesalahan tak terduga")

    @test_app.get("/with-body")
    async def with_body(value: int):  # type: ignore[no-untyped-def]
        return {"value": value}

    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_app_error_handler_returns_mapped_status_and_body(client: TestClient) -> None:
    response = client.get("/raise-app-error")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "ZONE_NOT_FOUND"
    assert body["error"]["message"] == "Zone 'x' tidak ditemukan."
    assert body["error"]["details"] == {"name": "x"}
    assert "request_id" in body


def test_validation_error_handler_returns_422(client: TestClient) -> None:
    response = client.get("/with-body", params={"value": "bukan-angka"})
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert "errors" in body["error"]["details"]


def test_unexpected_exception_handler_returns_500_without_leaking_internals(client: TestClient) -> None:
    response = client.get("/raise-unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "kesalahan tak terduga" not in body["error"]["message"]  # detail internal tidak bocor ke client
    assert body["error"]["message"] == "Terjadi kesalahan internal pada server."


def test_error_response_includes_request_id_even_without_middleware(client: TestClient) -> None:
    """Tanpa middleware request-id (app minimal di sini), handler tetap menghasilkan
    request_id fallback (UUID baru) alih-alih error/absen."""
    response = client.get("/raise-app-error")
    request_id = response.json()["request_id"]
    assert len(request_id) > 0
