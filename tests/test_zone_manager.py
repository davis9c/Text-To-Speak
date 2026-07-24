"""Unit test untuk ZoneManager (Phase 6).

Memakai ``TTSConfig`` dengan ``FakeEngine`` (pola yang sama seperti
``test_pipeline_processor.py``) supaya tidak butuh binary Piper sungguhan,
dan ``audio_device_manager=None`` untuk test yang tidak butuh Playback
sungguhan (playback_manager otomatis None di setiap zone, sama seperti
perilaku graceful Phase 4/5 saat PortAudio tidak terdeteksi).
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import (
    ValidationAppError,
    ZoneAlreadyExistsError,
    ZoneNotFoundError,
    ZoneProtectedError,
)
from announcement_server.queueing.models import QueuePriority
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
    EngineFactory.register("fake_zone_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_zone_engine"]


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_zone_engine", cache_dir=str(tmp_path / "cache"))
    return TTSService(config)


@pytest.fixture()
async def zone_manager(tts_service: TTSService):
    manager = ZoneManager(audio_device_manager=None, tts_service=tts_service)
    yield manager
    await manager.shutdown()


async def test_create_zone_registers_it(zone_manager: ZoneManager) -> None:
    zone = await zone_manager.create_zone("lobby")
    assert zone.name == "lobby"
    assert zone.enabled is True
    assert zone.volume == 1.0
    assert zone.device_id is None

    listed = zone_manager.list_zones()
    assert [z.name for z in listed] == ["lobby"]


async def test_create_zone_duplicate_name_raises_409(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby")
    with pytest.raises(ZoneAlreadyExistsError):
        await zone_manager.create_zone("lobby")


async def test_create_zone_invalid_name_raises_validation_error(zone_manager: ZoneManager) -> None:
    with pytest.raises(ValidationAppError):
        await zone_manager.create_zone("nama zone tidak valid!!")


async def test_create_zone_disabled_does_not_start_worker(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby", enabled=False)
    assert zone_manager.is_worker_running("lobby") is False


async def test_create_zone_enabled_starts_worker(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby", enabled=True)
    assert zone_manager.is_worker_running("lobby") is True
    await zone_manager.delete_zone("lobby")


async def test_get_zone_unknown_raises_404(zone_manager: ZoneManager) -> None:
    with pytest.raises(ZoneNotFoundError):
        zone_manager.get_zone("tidak-ada")


async def test_update_zone_enabled_toggles_worker(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby", enabled=True)
    assert zone_manager.is_worker_running("lobby") is True

    await zone_manager.update_zone("lobby", enabled=False)
    assert zone_manager.is_worker_running("lobby") is False

    await zone_manager.update_zone("lobby", enabled=True)
    assert zone_manager.is_worker_running("lobby") is True
    await zone_manager.delete_zone("lobby")


async def test_update_zone_volume_partial_update(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby", volume=1.0)
    updated = await zone_manager.update_zone("lobby", volume=0.5)
    assert updated.volume == 0.5
    assert updated.enabled is True  # tidak berubah karena tidak dikirim


async def test_update_zone_unknown_raises_404(zone_manager: ZoneManager) -> None:
    with pytest.raises(ZoneNotFoundError):
        await zone_manager.update_zone("tidak-ada", volume=0.5)


async def test_delete_zone_removes_it(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby")
    await zone_manager.delete_zone("lobby")
    with pytest.raises(ZoneNotFoundError):
        zone_manager.get_zone("lobby")


async def test_delete_main_zone_is_protected(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone(MAIN_ZONE_NAME)
    with pytest.raises(ZoneProtectedError):
        await zone_manager.delete_zone(MAIN_ZONE_NAME)


async def test_delete_unknown_zone_raises_404(zone_manager: ZoneManager) -> None:
    with pytest.raises(ZoneNotFoundError):
        await zone_manager.delete_zone("tidak-ada")


async def test_each_zone_has_independent_queue_manager(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby")
    await zone_manager.create_zone("produksi")

    lobby_queue = zone_manager.get_queue_manager("lobby")
    produksi_queue = zone_manager.get_queue_manager("produksi")
    assert lobby_queue is not produksi_queue

    await lobby_queue.enqueue("Hanya di lobby", QueuePriority.NORMAL)
    lobby_items = await lobby_queue.list_items()
    produksi_items = await produksi_queue.list_items()
    assert len(lobby_items) == 1
    assert len(produksi_items) == 0


async def test_playback_manager_is_none_when_audio_device_manager_is_none(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby")
    assert zone_manager.get_playback_manager("lobby") is None
    assert zone_manager.get_playback_state("lobby") is None


async def test_shutdown_stops_all_zone_workers(zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby")
    await zone_manager.create_zone("produksi")
    assert zone_manager.is_worker_running("lobby") is True
    assert zone_manager.is_worker_running("produksi") is True

    await zone_manager.shutdown()

    assert zone_manager.is_worker_running("lobby") is False
    assert zone_manager.is_worker_running("produksi") is False
