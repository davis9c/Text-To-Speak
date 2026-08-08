"""Test untuk fitur Chime (opsional) — field `chime` pada POST /speak, /zones, dan /scheduler.

Fitur: efek chime berupa file audio statis (mis. ``sounds/chime.wav``) yang
diputar SEKALI SEBELUM pengumuman utama. Bersifat OPSIONAL: jika field
`chime` tidak dikirim (null), perilaku identik seperti sebelum fitur ini ada.

Test di file ini hanya memverifikasi layer HTTP/schema (validasi 201/422 +
mapping response, termasuk ke `QueueItem` domain lewat `trigger`) —
pemutaran chime yang sebenarnya diverifikasi di ``test_pipeline_chime.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from announcement_server.api.deps import get_queue_manager
from announcement_server.core.config import get_settings
from announcement_server.main import create_app
from announcement_server.queueing.manager import QueueManager


@pytest.fixture()
def isolated_manager() -> QueueManager:
    return QueueManager(max_size=10, max_history=10)


@pytest.fixture()
def client(isolated_manager: QueueManager) -> Iterator[TestClient]:
    """Client dengan QueueManager main ter-isolasi — item yang di-enqueue TIDAK
    diproses otomatis oleh worker, sehingga status PENDING bisa diverifikasi
    secara deterministik (pola sama seperti test_queue_api.py)."""
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_queue_manager] = lambda: isolated_manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture()
def live_client() -> Iterator[TestClient]:
    """Client app sungguhan (tanpa dependency override) — untuk endpoint yang
    memakai ZoneManager/SchedulerManager (zone & scheduler)."""
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


# --- POST /speak -------------------------------------------------------------


def test_speak_with_chime_returns_201_and_echoes_chime(client: TestClient) -> None:
    response = client.post("/speak", json={"text": "Halo dunia", "chime": "chime.wav"})
    assert response.status_code == 201
    body = response.json()
    assert body["chime"] == "chime.wav"
    assert body["status"] == "pending"


def test_speak_without_chime_returns_chime_null(client: TestClient) -> None:
    """Regresi: payload lama (tanpa `chime`) tetap valid — chime null, tidak ada perilaku baru."""
    response = client.post("/speak", json={"text": "Halo dunia"})
    assert response.status_code == 201
    assert response.json()["chime"] is None


def test_speak_chime_works_for_audio_type(client: TestClient) -> None:
    response = client.post(
        "/speak",
        json={"type": "audio", "file": "bell.wav", "chime": "chime.wav", "priority": "high"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["chime"] == "chime.wav"
    assert body["type"] == "audio"


def test_speak_chime_too_long_returns_422(client: TestClient) -> None:
    response = client.post("/speak", json={"text": "Halo", "chime": "x" * 501})
    assert response.status_code == 422


def test_get_queue_returns_chime_field(client: TestClient) -> None:
    client.post("/speak", json={"text": "Halo", "chime": "chime.wav"})
    response = client.get("/queue")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["chime"] == "chime.wav"


# --- POST /zones/{name}/speak --------------------------------------------------


def test_zone_speak_echoes_chime(live_client: TestClient) -> None:
    response = live_client.post(
        "/zones/main/speak", json={"text": "Pengumuman di zone main", "chime": "chime.wav"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["chime"] == "chime.wav"
    assert body["status"] == "pending"


# --- /scheduler ----------------------------------------------------------------


_SCHEDULE_WITH_CHIME = {
    "name": "Pengumuman Chime",
    "zone": "main",
    "recurrence": "daily",
    "time_of_day": "07:00",
    "announcement": {"type": "tts", "text": "Halo", "chime": "chime.wav"},
}


def test_scheduler_create_preserves_chime_in_announcement(live_client: TestClient) -> None:
    response = live_client.post("/scheduler", json=_SCHEDULE_WITH_CHIME)
    assert response.status_code == 201
    announcement = response.json()["announcement"]
    assert announcement["type"] == "tts"
    assert announcement["chime"] == "chime.wav"


def test_scheduler_trigger_enqueues_item_with_chime(live_client: TestClient) -> None:
    created = live_client.post("/scheduler", json=_SCHEDULE_WITH_CHIME).json()
    response = live_client.post(f"/scheduler/{created['id']}/trigger")
    assert response.status_code == 201
    body = response.json()
    assert body["chime"] == "chime.wav"
    assert body["status"] == "pending"
