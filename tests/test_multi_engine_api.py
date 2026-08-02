"""Test HTTP untuk field `engine` pada POST /speak (V2 Phase 2 — Multi-Engine Architecture).

Hanya menguji request/response `/speak` (enqueue murni, sinkron) — pemrosesan
TTS sesungguhnya terjadi asinkron di worker (di luar scope endpoint ini),
mengikuti pola yang sama dengan `test_speak_announcement_type_api.py`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_speak_without_engine_field_is_backward_compatible(client: TestClient) -> None:
    """Payload V1 (tanpa `engine`) HARUS tetap diterima, `engine` pada response bernilai null."""
    response = client.post("/speak", json={"text": "Halo dunia"})
    assert response.status_code == 201
    body = response.json()
    assert body["engine"] is None


def test_speak_with_explicit_engine_field_is_accepted_and_stored(client: TestClient) -> None:
    response = client.post("/speak", json={"text": "Halo dunia", "engine": "piper"})
    assert response.status_code == 201
    body = response.json()
    assert body["engine"] == "piper"


def test_queue_item_response_reflects_stored_engine(client: TestClient) -> None:
    create_response = client.post("/speak", json={"text": "Cek antrean", "engine": "piper"})
    item_id = create_response.json()["id"]

    queue_response = client.get("/queue")
    assert queue_response.status_code == 200
    items = {item["id"]: item for item in queue_response.json()["items"]}
    assert items[item_id]["engine"] == "piper"


# --- RC1-5: resource limit pada field engine/voice --------------------------------


def test_speak_rejects_excessively_long_engine_name(client: TestClient) -> None:
    """RC1-5: `engine`/`voice` sebelumnya tidak dibatasi panjangnya (berbeda dari `text`/`file`
    yang sudah punya `max_length`) -- sekarang dibatasi 200 karakter, jauh lebih dari cukup
    untuk identifier engine/voice yang sesungguhnya (mis. 'piper', 'en_US-lessac-medium')."""
    response = client.post("/speak", json={"text": "Halo", "engine": "x" * 201})
    assert response.status_code == 422


def test_speak_rejects_excessively_long_voice_name(client: TestClient) -> None:
    response = client.post("/speak", json={"text": "Halo", "voice": "x" * 201})
    assert response.status_code == 422


def test_speak_accepts_engine_and_voice_at_length_boundary(client: TestClient) -> None:
    """Memastikan batas 200 karakter tidak sengaja terlalu ketat untuk nama voice/engine wajar."""
    response = client.post("/speak", json={"text": "Halo", "engine": "x" * 200, "voice": "y" * 200})
    assert response.status_code == 201
