"""Unit test untuk main.py (Phase 13 — coverage gap-fill): middleware, router registration, 404.

Memakai fixture ``client`` dari ``conftest.py`` (app sungguhan via
``create_app()``) — fokus di sini KHUSUS pada perilaku level aplikasi
(bukan business logic endpoint, yang sudah diuji lengkap di
``test_*_api.py`` masing-masing fase).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


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
