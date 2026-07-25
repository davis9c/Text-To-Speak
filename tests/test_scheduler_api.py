"""Test HTTP untuk Phase 8 (Scheduler) — `/scheduler` endpoints.

``SchedulerManager`` (dan ``ZoneManager`` di baliknya) di-override lewat
``app.dependency_overrides`` menjadi instance terisolasi (pola sama
seperti ``test_zones_api.py``) — supaya tidak terpengaruh oleh 3 contoh
jadwal (disabled) yang sudah dimuat dari `config/config.yaml` yang
sesungguhnya, dan tidak butuh Piper/hardware audio sungguhan.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.api.deps import get_scheduler_manager
from announcement_server.core.config import AnnouncementConfig, TTSConfig, get_settings
from announcement_server.main import create_app
from announcement_server.scheduler.manager import SchedulerManager
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService
from announcement_server.zones.manager import ZoneManager
from announcement_server.zones.models import MAIN_ZONE_NAME


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
    EngineFactory.register("fake_scheduler_api_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_scheduler_api_engine"]


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_scheduler_api_engine", cache_dir=str(tmp_path / "cache"))
    return TTSService(config)


@pytest.fixture()
def asset_resolver(tmp_path: Path) -> AudioAssetResolver:
    config = AnnouncementConfig(
        sounds_dir=str(tmp_path / "sounds"),
        converted_cache_dir=str(tmp_path / "cache_announcement"),
    )
    return AudioAssetResolver(config)


@pytest.fixture()
async def isolated_zone_manager(tts_service: TTSService, asset_resolver: AudioAssetResolver) -> Iterator[ZoneManager]:
    manager = ZoneManager(audio_device_manager=None, tts_service=tts_service, asset_resolver=asset_resolver)
    await manager.create_zone(MAIN_ZONE_NAME)
    yield manager
    await manager.shutdown()


@pytest.fixture()
async def isolated_scheduler_manager(isolated_zone_manager: ZoneManager) -> Iterator[SchedulerManager]:
    manager = SchedulerManager(isolated_zone_manager, default_voice="default", poll_interval_seconds=0.1)
    yield manager
    await manager.shutdown()


@pytest.fixture()
def client(isolated_scheduler_manager: SchedulerManager) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_scheduler_manager] = lambda: isolated_scheduler_manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


_TTS_BODY = {
    "name": "Bell Masuk",
    "zone": "main",
    "recurrence": "daily",
    "time_of_day": "07:00",
    "announcement": {"type": "tts", "text": "Selamat pagi"},
}


# --- GET /scheduler & POST /scheduler ---------------------------------------


def test_list_schedules_starts_empty(client: TestClient) -> None:
    response = client.get("/scheduler")
    assert response.status_code == 200
    assert response.json() == {"schedules": [], "count": 0}


def test_create_schedule_returns_201(client: TestClient) -> None:
    response = client.post("/scheduler", json=_TTS_BODY)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Bell Masuk"
    assert body["recurrence"] == "daily"
    assert body["enabled"] is True
    assert body["announcement"]["type"] == "tts"
    assert body["announcement"]["text"] == "Selamat pagi"
    assert body["next_run_at"] is not None


def test_create_schedule_audio_type(client: TestClient) -> None:
    body = {
        "name": "Bell",
        "recurrence": "daily",
        "time_of_day": "07:00",
        "announcement": {"type": "audio", "file": "sounds/bell.mp3", "priority": "high"},
    }
    response = client.post("/scheduler", json=body)
    assert response.status_code == 201
    announcement = response.json()["announcement"]
    assert announcement["type"] == "audio"
    assert announcement["file"] == "sounds/bell.mp3"
    assert announcement["text"] == "[audio] sounds/bell.mp3"  # auto-generated (Phase 7 resolved_text)


def test_create_schedule_weekly_missing_days_returns_422(client: TestClient) -> None:
    body = {**_TTS_BODY, "recurrence": "weekly"}
    response = client.post("/scheduler", json=body)
    assert response.status_code == 422


def test_create_schedule_once_missing_run_date_returns_422(client: TestClient) -> None:
    body = {**_TTS_BODY, "recurrence": "once"}
    response = client.post("/scheduler", json=body)
    assert response.status_code == 422


def test_create_schedule_once_past_date_returns_422(client: TestClient) -> None:
    body = {**_TTS_BODY, "recurrence": "once", "run_date": "2020-01-01"}
    response = client.post("/scheduler", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SCHEDULE"


def test_create_schedule_tts_without_text_returns_422(client: TestClient) -> None:
    body = {**_TTS_BODY, "announcement": {"type": "tts"}}
    response = client.post("/scheduler", json=body)
    assert response.status_code == 422


def test_list_schedules_after_create(client: TestClient) -> None:
    client.post("/scheduler", json=_TTS_BODY)
    response = client.get("/scheduler")
    assert response.json()["count"] == 1


# --- GET /scheduler/{id} -----------------------------------------------------


def test_get_schedule_returns_detail(client: TestClient) -> None:
    created = client.post("/scheduler", json=_TTS_BODY).json()
    response = client.get(f"/scheduler/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Bell Masuk"


def test_get_schedule_unknown_returns_404(client: TestClient) -> None:
    response = client.get("/scheduler/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCHEDULE_NOT_FOUND"


def test_get_schedule_invalid_uuid_returns_422(client: TestClient) -> None:
    response = client.get("/scheduler/bukan-uuid")
    assert response.status_code == 422


# --- PUT /scheduler/{id} ------------------------------------------------------


def test_update_schedule_enabled(client: TestClient) -> None:
    created = client.post("/scheduler", json=_TTS_BODY).json()
    response = client.put(f"/scheduler/{created['id']}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_update_schedule_announcement(client: TestClient) -> None:
    created = client.post("/scheduler", json=_TTS_BODY).json()
    response = client.put(
        f"/scheduler/{created['id']}", json={"announcement": {"type": "tts", "text": "Teks baru"}}
    )
    assert response.status_code == 200
    assert response.json()["announcement"]["text"] == "Teks baru"


def test_update_schedule_unknown_returns_404(client: TestClient) -> None:
    response = client.put("/scheduler/00000000-0000-0000-0000-000000000000", json={"enabled": False})
    assert response.status_code == 404


# --- DELETE /scheduler/{id} ---------------------------------------------------


def test_delete_schedule_removes_it(client: TestClient) -> None:
    created = client.post("/scheduler", json=_TTS_BODY).json()
    response = client.delete(f"/scheduler/{created['id']}")
    assert response.status_code == 200
    assert response.json() == {"id": created["id"], "deleted": True}
    assert client.get("/scheduler").json()["count"] == 0


def test_delete_schedule_unknown_returns_404(client: TestClient) -> None:
    response = client.delete("/scheduler/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# --- POST /scheduler/{id}/trigger --------------------------------------------


def test_trigger_schedule_enqueues_item(client: TestClient) -> None:
    created = client.post("/scheduler", json=_TTS_BODY).json()
    response = client.post(f"/scheduler/{created['id']}/trigger")
    assert response.status_code == 201
    body = response.json()
    assert body["text"] == "Selamat pagi"
    assert body["status"] == "pending"

    # next_run_at TIDAK berubah karena trigger manual.
    unchanged = client.get(f"/scheduler/{created['id']}").json()
    assert unchanged["next_run_at"] == created["next_run_at"]


def test_trigger_schedule_unknown_returns_404(client: TestClient) -> None:
    response = client.post("/scheduler/00000000-0000-0000-0000-000000000000/trigger")
    assert response.status_code == 404
