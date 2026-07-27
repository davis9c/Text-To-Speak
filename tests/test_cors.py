"""Test untuk CORS middleware — memastikan dashboard/tester HTML terpisah (index.html)
bisa memanggil API ini dari origin lain (file:// atau port lain) tanpa diblokir browser."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_simple_get_includes_cors_header(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:5500"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"


def test_preflight_options_request_is_handled(client: TestClient) -> None:
    response = client.options(
        "/speak",
        headers={
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"
    assert "POST" in response.headers.get("access-control-allow-methods", "")


def test_post_request_with_origin_includes_cors_header(client: TestClient) -> None:
    response = client.post("/speak", json={"text": "Halo"}, headers={"Origin": "http://localhost:5500"})
    assert response.headers.get("access-control-allow-origin") == "*"


def test_request_id_header_is_exposed_for_cors(client: TestClient) -> None:
    """`X-Request-ID`/`X-Process-Time-Ms` harus ada di `Access-Control-Expose-Headers`
    supaya JS di browser (fetch) bisa membacanya lewat `response.headers.get(...)`."""
    response = client.get("/health", headers={"Origin": "http://localhost:5500"})
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "X-Request-ID" in exposed
