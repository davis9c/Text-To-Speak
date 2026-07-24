"""Test untuk layer HTTP Audio Playback.

Sama seperti test_queue_api.py, AudioDeviceManager & PlaybackManager
di-override lewat ``app.dependency_overrides`` dengan instance yang
memakai fake sounddevice module — sehingga test ini tidak butuh hardware
audio maupun PortAudio sungguhan.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.api.deps import get_audio_device_manager, get_playback_manager
from announcement_server.core.config import get_settings
from announcement_server.main import create_app
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.playback.manager import PlaybackManager

from tests.test_playback_manager import FakeSoundDevice, _make_wav_bytes


@pytest.fixture(autouse=True)
def reset_fake_streams():
    FakeSoundDevice.created_streams = []
    yield


@pytest.fixture()
def isolated_device_manager() -> AudioDeviceManager:
    return AudioDeviceManager(sd_module=FakeSoundDevice)


@pytest.fixture()
def isolated_playback_manager(isolated_device_manager: AudioDeviceManager) -> PlaybackManager:
    return PlaybackManager(isolated_device_manager, sd_module=FakeSoundDevice)


@pytest.fixture()
def client(
    isolated_device_manager: AudioDeviceManager, isolated_playback_manager: PlaybackManager
) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_audio_device_manager] = lambda: isolated_device_manager
    app.dependency_overrides[get_playback_manager] = lambda: isolated_playback_manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_get_devices_returns_output_devices_only(client: TestClient) -> None:
    response = client.get("/devices")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["devices"][0]["name"] == "Fake Speaker"
    assert body["devices"][0]["max_output_channels"] == 2


def test_select_device_success(client: TestClient) -> None:
    response = client.post("/device", json={"device_id": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["selected_device_id"] == 0
    assert body["state"] == "idle"


def test_select_unknown_device_returns_404(client: TestClient) -> None:
    response = client.post("/device", json={"device_id": 999})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUDIO_DEVICE_NOT_FOUND"


def test_pause_when_idle_returns_409(client: TestClient) -> None:
    response = client.post("/pause")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAYBACK_STATE_ERROR"


def test_resume_when_idle_returns_409(client: TestClient) -> None:
    response = client.post("/resume")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAYBACK_STATE_ERROR"


def test_stop_when_idle_is_idempotent_200(client: TestClient) -> None:
    response = client.post("/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "idle"
    assert body["current_file"] is None


def test_full_playback_control_flow(client: TestClient, isolated_playback_manager: PlaybackManager, tmp_path: Path) -> None:
    """Simulasi alur penuh: play (lewat manager langsung) -> pause via HTTP -> resume via HTTP -> stop via HTTP.

    Playback sendiri dipicu langsung lewat manager (BUKAN lewat endpoint HTTP,
    karena Phase 4 sengaja tidak menyediakan endpoint "play" — lihat roadmap),
    lalu kontrolnya (pause/resume/stop) diverifikasi lewat HTTP endpoint yang
    sesungguhnya, memastikan endpoint benar-benar memanipulasi instance
    PlaybackManager yang sama dengan yang di-inject lewat dependency override.
    """
    import asyncio

    wav_path = tmp_path / "announcement.wav"
    wav_path.write_bytes(_make_wav_bytes(n_frames=500))

    asyncio.run(isolated_playback_manager.play(str(wav_path)))

    pause_response = client.post("/pause")
    assert pause_response.status_code == 200
    assert pause_response.json()["state"] == "paused"
    assert pause_response.json()["current_file"] == str(wav_path)

    resume_response = client.post("/resume")
    assert resume_response.status_code == 200
    assert resume_response.json()["state"] == "playing"

    stop_response = client.post("/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["state"] == "idle"
    assert stop_response.json()["current_file"] is None


def test_select_device_rejects_non_integer_device_id(client: TestClient) -> None:
    response = client.post("/device", json={"device_id": "bukan-angka"})
    assert response.status_code == 422


def test_select_device_missing_field_returns_422(client: TestClient) -> None:
    response = client.post("/device", json={})
    assert response.status_code == 422
