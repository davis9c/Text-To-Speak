"""Test untuk GET /health."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_body(client: TestClient) -> None:
    response = client.get("/health")
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "Announcement Server"
    assert "version" in body
    assert body["environment"] in {"development", "staging", "production"}


def test_health_has_request_id_header(client: TestClient) -> None:
    response = client.get("/health")
    assert "X-Request-ID" in response.headers
    assert "X-Process-Time-Ms" in response.headers


def test_404_uses_consistent_error_envelope(client: TestClient) -> None:
    response = client.get("/this-route-does-not-exist")
    assert response.status_code == 404
