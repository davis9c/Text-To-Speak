"""Test untuk layer HTTP Multi Zone (Phase 6).

Sama seperti ``test_queue_api.py``/``test_playback_api.py``, ``ZoneManager``
di-override lewat ``app.dependency_overrides`` menjadi instance terpisah
dari yang dipakai lifespan aplikasi (yang membangun TTSService dengan
engine sungguhan dari config.yaml, mis. Piper). Instance terisolasi ini
memakai ``FakeEngine`` (tidak butuh binary Piper) dan
``AudioDeviceManager``/``PlaybackManager`` dengan ``FakeSoundDevice``
(tidak butuh hardware audio) — persis pola yang sudah dipakai
``test_playback_api.py``.

Zone "main" SENGAJA sudah dibuat di fixture ``isolated_zone_manager`` agar
mencerminkan perilaku nyata aplikasi (zone main selalu ada sejak startup)
dan supaya test proteksi ``DELETE /zones/main`` bisa diverifikasi.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.api.deps import get_zone_manager
from announcement_server.core.config import TTSConfig, get_settings
from announcement_server.main import create_app
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService
from announcement_server.zones.manager import ZoneManager
from announcement_server.zones.models import MAIN_ZONE_NAME

from tests.test_playback_manager import FakeSoundDevice


class FakeEngine(TTSEngine):
    """Engine TTS palsu: menghasilkan WAV valid tanpa memanggil Piper asli."""

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(22050)
            writer.writeframes(b"\x00\x00" * 50)
        return buffer.getvalue()


@pytest.fixture(autouse=True)
def register_fake_engine():
    EngineFactory.register("fake_zones_api_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_zones_api_engine"]


@pytest.fixture(autouse=True)
def reset_fake_streams():
    FakeSoundDevice.created_streams = []
    yield


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_zones_api_engine", cache_dir=str(tmp_path / "cache"))
    return TTSService(config)


@pytest.fixture()
def isolated_audio_device_manager() -> AudioDeviceManager:
    return AudioDeviceManager(sd_module=FakeSoundDevice)


@pytest.fixture()
async def isolated_zone_manager(
    tts_service: TTSService, isolated_audio_device_manager: AudioDeviceManager
) -> Iterator[ZoneManager]:
    manager = ZoneManager(audio_device_manager=isolated_audio_device_manager, tts_service=tts_service)
    await manager.create_zone(MAIN_ZONE_NAME)
    yield manager
    await manager.shutdown()


@pytest.fixture()
def client(isolated_zone_manager: ZoneManager) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_zone_manager] = lambda: isolated_zone_manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


# --- GET /zones & POST /zones -----------------------------------------------


def test_list_zones_includes_main_by_default(client: TestClient) -> None:
    response = client.get("/zones")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["zones"][0]["name"] == MAIN_ZONE_NAME
    assert body["zones"][0]["enabled"] is True
    assert body["zones"][0]["worker_running"] is True
    assert body["zones"][0]["pending_count"] == 0


def test_create_zone_returns_201(client: TestClient) -> None:
    response = client.post("/zones", json={"name": "lobby", "volume": 0.8, "enabled": True})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "lobby"
    assert body["volume"] == 0.8
    assert body["enabled"] is True
    assert body["worker_running"] is True
    assert body["pending_count"] == 0


def test_create_zone_disabled_worker_not_running(client: TestClient) -> None:
    response = client.post("/zones", json={"name": "lobby", "enabled": False})
    assert response.status_code == 201
    assert response.json()["worker_running"] is False


def test_create_zone_duplicate_name_returns_409(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    response = client.post("/zones", json={"name": "lobby"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ZONE_ALREADY_EXISTS"


def test_create_zone_invalid_name_returns_422(client: TestClient) -> None:
    response = client.post("/zones", json={"name": "nama tidak valid!!"})
    assert response.status_code == 422


def test_list_zones_after_create_shows_both(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    response = client.get("/zones")
    body = response.json()
    assert body["count"] == 2
    assert {zone["name"] for zone in body["zones"]} == {MAIN_ZONE_NAME, "lobby"}


# --- PUT /zones/{name} -------------------------------------------------------


def test_update_zone_volume(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    response = client.put("/zones/lobby", json={"volume": 0.3})
    assert response.status_code == 200
    assert response.json()["volume"] == 0.3


def test_update_zone_enabled_stops_worker(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    response = client.put("/zones/lobby", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["worker_running"] is False


def test_update_unknown_zone_returns_404(client: TestClient) -> None:
    response = client.put("/zones/tidak-ada", json={"volume": 0.5})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ZONE_NOT_FOUND"


# --- DELETE /zones/{name} ----------------------------------------------------


def test_delete_zone_removes_it(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    response = client.delete("/zones/lobby")
    assert response.status_code == 200
    assert response.json() == {"name": "lobby", "deleted": True}

    listing = client.get("/zones")
    assert listing.json()["count"] == 1


def test_delete_main_zone_returns_409(client: TestClient) -> None:
    response = client.delete(f"/zones/{MAIN_ZONE_NAME}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ZONE_PROTECTED"


def test_delete_unknown_zone_returns_404(client: TestClient) -> None:
    response = client.delete("/zones/tidak-ada")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ZONE_NOT_FOUND"


# --- GET /zones/{name}/queue & POST /zones/{name}/speak ---------------------


def test_zone_queue_starts_empty(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    response = client.get("/zones/lobby/queue")
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_speak_to_zone_adds_item_to_that_zone_only(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    client.post("/zones", json={"name": "produksi"})

    speak_response = client.post("/zones/lobby/speak", json={"text": "Halo dari lobby"})
    assert speak_response.status_code == 201
    body = speak_response.json()
    assert body["text"] == "Halo dari lobby"

    lobby_queue = client.get("/zones/lobby/queue")
    assert lobby_queue.json()["count"] == 1

    produksi_queue = client.get("/zones/produksi/queue")
    assert produksi_queue.json()["count"] == 0

    main_queue = client.get("/queue")
    assert main_queue.json()["count"] == 0


def test_speak_to_disabled_zone_returns_409(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby", "enabled": False})
    response = client.post("/zones/lobby/speak", json={"text": "Tidak akan masuk"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ZONE_DISABLED"


def test_speak_to_unknown_zone_returns_404(client: TestClient) -> None:
    response = client.post("/zones/tidak-ada/speak", json={"text": "Halo"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ZONE_NOT_FOUND"


def test_speak_to_main_endpoint_does_not_affect_lobby_zone(client: TestClient) -> None:
    """Memastikan POST /speak (Phase 2, tidak diubah) tetap hanya menyasar zone 'main'."""
    client.post("/zones", json={"name": "lobby"})
    client.post("/speak", json={"text": "Hanya untuk main"})

    assert client.get("/queue").json()["count"] == 1
    assert client.get("/zones/lobby/queue").json()["count"] == 0


# --- POST /zones/{name}/device ----------------------------------------------


def test_select_zone_device_returns_status(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    response = client.post("/zones/lobby/device", json={"device_id": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["selected_device_id"] == 0
    assert body["state"] == "idle"

    zone_response = client.get("/zones")
    lobby = next(zone for zone in zone_response.json()["zones"] if zone["name"] == "lobby")
    assert lobby["device_id"] == 0


def test_select_zone_device_unknown_device_returns_404(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    response = client.post("/zones/lobby/device", json={"device_id": 999})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUDIO_DEVICE_NOT_FOUND"


def test_select_device_unknown_zone_returns_404(client: TestClient) -> None:
    response = client.post("/zones/tidak-ada/device", json={"device_id": 0})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ZONE_NOT_FOUND"
