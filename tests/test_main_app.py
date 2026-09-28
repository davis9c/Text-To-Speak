"""Unit test untuk main.py (Phase 13 — coverage gap-fill): middleware, router registration, 404.

Memakai fixture ``client`` dari ``conftest.py`` (app sungguhan via
``create_app()``) — fokus di sini KHUSUS pada perilaku level aplikasi
(bukan business logic endpoint, yang sudah diuji lengkap di
``test_*_api.py`` masing-masing fase).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from announcement_server.core.config import get_settings
from announcement_server.core.exceptions import TTSEngineNotAvailableError
from announcement_server.main import create_app


def test_response_includes_request_id_header(client: TestClient) -> None:
    response = client.get("/health")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_response_includes_process_time_header(client: TestClient) -> None:
    response = client.get("/health")
    assert "X-Process-Time-Ms" in response.headers
    assert float(response.headers["X-Process-Time-Ms"]) >= 0


def test_request_id_is_unique_per_request(client: TestClient) -> None:
    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]
    assert first != second


def test_unknown_route_returns_404(client: TestClient) -> None:
    response = client.get("/rute-tidak-ada")
    assert response.status_code == 404


def test_all_expected_routers_are_registered(client: TestClient) -> None:
    """Spot-check satu endpoint representatif dari SETIAP router (Phase 1-10) benar-benar terdaftar."""
    assert client.get("/health").status_code == 200
    assert client.get("/queue").status_code == 200
    assert client.get("/devices").status_code == 200
    assert client.get("/zones").status_code == 200
    assert client.get("/scheduler").status_code == 200
    assert client.get("/status").status_code == 200
    assert client.get("/history").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_openapi_schema_is_generated(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/health" in schema["paths"]
    assert "/speak" in schema["paths"]


def test_docs_page_available(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200


def test_large_response_is_gzip_compressed(client: TestClient) -> None:
    """(Phase 14) Response cukup besar (openapi.json) harus dikompresi saat client mendukung gzip."""
    response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"


# --- RC1-6: startup gagal-jelas untuk konfigurasi salah ---------------------------


def test_startup_fails_clearly_when_tts_engine_is_unregistered(monkeypatch: pytest.MonkeyPatch) -> None:
    """RC1-6: menutup celah nyata -- sebelumnya TIDAK ADA test yang benar-benar menjalankan
    `create_app()` end-to-end dengan config bermasalah untuk memverifikasi klaim RC1-1/RC1-4
    bahwa 'startup gagal dengan pesan yang jelas' jika `tts.engine` salah ketik/tidak terdaftar.
    Test ini membuktikan (bukan berasumsi) bahwa: (1) startup benar-benar gagal (bukan diam-diam
    lolos dengan state rusak), dan (2) exception yang terlempar informatif (menyebutkan nama
    engine yang diminta)."""
    monkeypatch.setenv("APP_TTS__ENGINE", "engine_yang_benar_benar_tidak_terdaftar")
    get_settings.cache_clear()
    app = create_app()

    with pytest.raises(TTSEngineNotAvailableError) as exc_info, TestClient(app):
        pass  # lifespan startup dijalankan saat TestClient di-__enter__, HARUS raise di sini

    assert exc_info.value.details["requested_engine"] == "engine_yang_benar_benar_tidak_terdaftar"
    get_settings.cache_clear()
