"""Test untuk layer HTTP Queue System.

QueueManager yang dipakai di test ini SENGAJA di-override lewat
``app.dependency_overrides`` menjadi instance terpisah dari yang dipakai
oleh QueueWorker milik aplikasi (yang berjalan otomatis lewat lifespan).
Dengan begitu, item yang di-enqueue lewat endpoint di test ini TIDAK akan
diproses otomatis oleh worker mana pun, sehingga status PENDING bisa
diverifikasi secara deterministik tanpa race condition.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from announcement_server.api.deps import get_queue_manager
from announcement_server.core.config import get_settings
from announcement_server.main import create_app
from announcement_server.queueing.manager import QueueManager


@pytest.fixture()
def isolated_manager() -> QueueManager:
    return QueueManager(max_size=3, max_history=10)


@pytest.fixture()
def client(isolated_manager: QueueManager) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_queue_manager] = lambda: isolated_manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_speak_returns_201_with_pending_status(client: TestClient) -> None:
    response = client.post("/speak", json={"text": "Nomor antrean A001", "priority": "normal"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["text"] == "Nomor antrean A001"
    assert body["priority"] == "normal"
    assert body["position"] == 1
    uuid.UUID(body["id"])  # tidak melempar error berarti format UUID valid


def test_speak_uses_normal_priority_by_default(client: TestClient) -> None:
    response = client.post("/speak", json={"text": "Tanpa priority eksplisit"})
    assert response.status_code == 201
    assert response.json()["priority"] == "normal"


def test_speak_rejects_empty_text(client: TestClient) -> None:
    response = client.post("/speak", json={"text": ""})
    assert response.status_code == 422


def test_speak_rejects_missing_text(client: TestClient) -> None:
    response = client.post("/speak", json={})
    assert response.status_code == 422


def test_get_queue_lists_pending_items_in_priority_order(client: TestClient) -> None:
    client.post("/speak", json={"text": "Biasa", "priority": "low"})
    client.post("/speak", json={"text": "Genting", "priority": "urgent"})

    response = client.get("/queue")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["items"][0]["priority"] == "urgent"
    assert body["items"][0]["position"] == 1
    assert body["items"][1]["priority"] == "low"
    assert body["items"][1]["position"] == 2


def test_get_queue_empty_by_default(client: TestClient) -> None:
    response = client.get("/queue")
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_delete_queue_item_cancels_pending_item(client: TestClient) -> None:
    speak_response = client.post("/speak", json={"text": "Akan dibatalkan"})
    item_id = speak_response.json()["id"]

    delete_response = client.delete(f"/queue/{item_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "cancelled"

    queue_response = client.get("/queue")
    assert queue_response.json()["count"] == 0  # cancelled tidak muncul di daftar aktif default


def test_delete_unknown_item_returns_404(client: TestClient) -> None:
    response = client.delete(f"/queue/{uuid.uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "QUEUE_ITEM_NOT_FOUND"


def test_delete_already_cancelled_item_returns_409(client: TestClient) -> None:
    speak_response = client.post("/speak", json={"text": "Dibatalkan dua kali"})
    item_id = speak_response.json()["id"]
    client.delete(f"/queue/{item_id}")

    second_delete = client.delete(f"/queue/{item_id}")
    assert second_delete.status_code == 409
    assert second_delete.json()["error"]["code"] == "QUEUE_ITEM_NOT_CANCELLABLE"


def test_clear_cancels_all_pending_items(client: TestClient) -> None:
    client.post("/speak", json={"text": "Item 1"})
    client.post("/speak", json={"text": "Item 2"})

    response = client.post("/clear")
    assert response.status_code == 200
    assert response.json()["cleared_count"] == 2

    assert client.get("/queue").json()["count"] == 0


def test_speak_returns_409_when_queue_full(client: TestClient) -> None:
    # isolated_manager dibuat dengan max_size=3
    for i in range(3):
        response = client.post("/speak", json={"text": f"Item {i}"})
        assert response.status_code == 201

    overflow_response = client.post("/speak", json={"text": "Item ke-4, seharusnya gagal"})
    assert overflow_response.status_code == 409
    assert overflow_response.json()["error"]["code"] == "QUEUE_FULL"


def test_invalid_uuid_in_path_returns_422(client: TestClient) -> None:
    response = client.delete("/queue/bukan-uuid-valid")
    assert response.status_code == 422
