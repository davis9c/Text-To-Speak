"""Test end-to-end untuk `/ws/status` (Phase 9).

``ZoneManager`` DAN ``ConnectionManager`` di-override lewat
``app.dependency_overrides`` menjadi instance terisolasi (pola sama
seperti ``test_zones_api.py``) — memakai ``FakeEngine``/``FakeSoundDevice``
supaya tidak butuh Piper/hardware audio sungguhan, dan supaya event yang
diterima lewat WebSocket bisa dipastikan berasal dari aksi test ini
sendiri (bukan lifespan aplikasi sungguhan).
"""

from __future__ import annotations

import io
import time
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.api.deps import get_queue_manager, get_zone_manager
from announcement_server.api.v1.websocket import get_connection_manager_ws, get_zone_manager_ws
from announcement_server.core.config import AnnouncementConfig, TTSConfig, get_settings
from announcement_server.main import create_app
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService
from announcement_server.websocket.manager import ConnectionManager
from announcement_server.zones.manager import ZoneManager
from announcement_server.zones.models import MAIN_ZONE_NAME

from tests.test_playback_manager import FakeSoundDevice


class FakeEngine(TTSEngine):
    """Engine TTS palsu: menghasilkan WAV valid tanpa memanggil Piper asli."""

    def __init__(self, config: TTSConfig) -> None:
        self.config = config

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
    EngineFactory.register("fake_ws_api_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_ws_api_engine"]


@pytest.fixture(autouse=True)
def reset_fake_streams():
    FakeSoundDevice.created_streams = []
    yield


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_ws_api_engine", cache_dir=str(tmp_path / "cache"))
    return TTSService(config)


@pytest.fixture()
def isolated_audio_device_manager() -> AudioDeviceManager:
    return AudioDeviceManager(sd_module=FakeSoundDevice)


@pytest.fixture()
def asset_resolver(tmp_path: Path) -> AudioAssetResolver:
    config = AnnouncementConfig(
        sounds_dir=str(tmp_path / "sounds"),
        converted_cache_dir=str(tmp_path / "cache_announcement"),
    )
    return AudioAssetResolver(config)


@pytest.fixture()
def isolated_connection_manager() -> ConnectionManager:
    return ConnectionManager()


@pytest.fixture()
async def isolated_zone_manager(
    tts_service: TTSService,
    isolated_audio_device_manager: AudioDeviceManager,
    asset_resolver: AudioAssetResolver,
    isolated_connection_manager: ConnectionManager,
) -> Iterator[ZoneManager]:
    manager = ZoneManager(
        audio_device_manager=isolated_audio_device_manager,
        tts_service=tts_service,
        asset_resolver=asset_resolver,
        event_publisher=isolated_connection_manager.broadcast,
    )
    await manager.create_zone(MAIN_ZONE_NAME)
    yield manager
    await manager.shutdown()


@pytest.fixture()
def client(isolated_zone_manager: ZoneManager, isolated_connection_manager: ConnectionManager) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_zone_manager] = lambda: isolated_zone_manager
    app.dependency_overrides[get_zone_manager_ws] = lambda: isolated_zone_manager
    app.dependency_overrides[get_connection_manager_ws] = lambda: isolated_connection_manager
    # `DELETE /queue/{id}` (Phase 2, endpoint global TANPA prefix zone) memakai dependency
    # `get_queue_manager` (bukan `get_zone_manager`) — di-override terpisah supaya beroperasi
    # pada QueueManager isolated zone "main" yang SAMA dengan yang dipakai `POST /zones/main/speak`.
    app.dependency_overrides[get_queue_manager] = lambda: isolated_zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_connect_receives_initial_snapshot(client: TestClient) -> None:
    with client.websocket_connect("/ws/status") as websocket:
        message = websocket.receive_json()
    assert message["event"] == "snapshot"
    assert "timestamp" in message
    zone_names = {zone["name"] for zone in message["data"]["zones"]}
    assert zone_names == {MAIN_ZONE_NAME}


def test_speak_broadcasts_queue_changed_event(client: TestClient) -> None:
    with client.websocket_connect("/ws/status") as websocket:
        websocket.receive_json()  # snapshot awal, dilewati

        response = client.post(f"/zones/{MAIN_ZONE_NAME}/speak", json={"text": "Halo dunia"})
        assert response.status_code == 201
        item_id = response.json()["id"]

        message = websocket.receive_json()

    assert message["event"] == "queue_changed"
    assert message["data"]["reason"] == "enqueued"
    assert message["data"]["item_id"] == item_id
    assert message["data"]["zone"] == MAIN_ZONE_NAME


def test_cancel_item_broadcasts_queue_changed_event(client: TestClient) -> None:
    created = client.post(f"/zones/{MAIN_ZONE_NAME}/speak", json={"text": "Akan dibatalkan"}).json()

    with client.websocket_connect("/ws/status") as websocket:
        websocket.receive_json()  # snapshot

        response = client.delete(f"/queue/{created['id']}")
        assert response.status_code == 200

        message = websocket.receive_json()

    assert message["event"] == "queue_changed"
    assert message["data"]["reason"] == "cancelled"
    assert message["data"]["item_id"] == created["id"]


def test_multiple_clients_all_receive_the_same_event(client: TestClient) -> None:
    with client.websocket_connect("/ws/status") as ws1, client.websocket_connect("/ws/status") as ws2:
        ws1.receive_json()  # snapshot
        ws2.receive_json()  # snapshot

        client.post(f"/zones/{MAIN_ZONE_NAME}/speak", json={"text": "Untuk semua client"})

        message_1 = ws1.receive_json()
        message_2 = ws2.receive_json()

    assert message_1["event"] == "queue_changed"
    assert message_2["event"] == "queue_changed"
    assert message_1["data"]["item_id"] == message_2["data"]["item_id"]


def test_disconnect_cleans_up_connection_registry(
    client: TestClient, isolated_connection_manager: ConnectionManager
) -> None:
    with client.websocket_connect("/ws/status") as websocket:
        websocket.receive_json()  # snapshot
        assert isolated_connection_manager.connection_count == 1

    # Starlette 0.41 TestClient menutup koneksi lewat cancel scope portal (bukan close
    # frame WS yang ditunggu server), sehingga `disconnect()` sisi server bisa menyusul
    # beberapa saat setelah blok `with` keluar -- tunggu sampai selesai secara
    # deterministik. (Kehandalan pembersihan itu sendiri dijamin oleh CancelScope
    # shield di api/v1/websocket.py: koneksi TIDAK akan pernah tertinggal di registry.)
    deadline = time.monotonic() + 5.0
    while isolated_connection_manager.connection_count > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert isolated_connection_manager.connection_count == 0


def test_unexpected_error_during_session_is_handled_and_cleans_up(
    isolated_connection_manager: ConnectionManager,
) -> None:
    """RC1-4: error TAK TERDUGA (bukan WebSocketDisconnect biasa, mis. bug pada zone_manager)
    HARUS tetap dibersihkan lewat `finally` (registry koneksi kembali kosong) dan TIDAK boleh
    membuat proses/test crash -- melengkapi `test_disconnect_cleans_up_connection_registry` yang
    hanya menguji jalur disconnect bersih."""

    class _BrokenZoneManager:
        def list_zones(self):  # noqa: ANN201 - test double sederhana, sengaja selalu melempar
            raise RuntimeError("simulasi bug tak terduga saat membangun snapshot awal")

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_zone_manager_ws] = lambda: _BrokenZoneManager()
    app.dependency_overrides[get_connection_manager_ws] = lambda: isolated_connection_manager
    with TestClient(app) as test_client:
        # Server menutup koneksi akibat exception tak tertangani di dalam handler --
        # client TIDAK BOLEH hang menunggu snapshot yang tidak akan pernah dikirim.
        with pytest.raises(Exception):  # noqa: B017,PT011 - detail exception client bervariasi antar versi Starlette
            with test_client.websocket_connect("/ws/status") as websocket:
                websocket.receive_json()

    assert isolated_connection_manager.connection_count == 0
    app.dependency_overrides.clear()
    get_settings.cache_clear()
