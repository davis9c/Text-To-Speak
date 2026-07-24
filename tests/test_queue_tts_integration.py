"""Test integrasi penuh: QueueManager + QueueWorker (Phase 2, tidak diubah) + TTSQueueProcessor (Phase 3).

Memverifikasi bahwa item yang di-enqueue dengan parameter TTS benar-benar
diproses lewat TTSService (via FakeEngine, bukan Piper asli) dan hasilnya
(``audio_file_path``, ``cache_hit``) tersimpan pada item sebelum statusnya
berubah menjadi COMPLETED.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueueItemStatus, QueuePriority
from announcement_server.queueing.tts_processor import TTSQueueProcessor
from announcement_server.queueing.worker import QueueWorker
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService


class FakeEngine(TTSEngine):
    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        import io
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(22050)
            writer.writeframes(b"\x00\x00" * 50)
        return buffer.getvalue()


@pytest.fixture(autouse=True)
def register_fake_engine():
    EngineFactory.register("fake_integration_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_integration_engine"]


async def _wait_until(condition, timeout: float = 2.0, interval: float = 0.01) -> None:
    elapsed = 0.0
    while not condition():
        if elapsed >= timeout:
            raise AssertionError("Timeout menunggu kondisi terpenuhi.")
        await asyncio.sleep(interval)
        elapsed += interval


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_integration_engine", cache_dir=str(tmp_path / "cache"))
    return TTSService(config)


async def test_item_gets_audio_file_path_after_processing(tts_service: TTSService) -> None:
    manager = QueueManager(max_size=10, max_history=10)
    processor = TTSQueueProcessor(tts_service, manager)
    worker = QueueWorker(manager, item_processor=processor)

    item = await manager.enqueue(
        "Nomor antrean A001",
        QueuePriority.NORMAL,
        voice="v1",
        speed=1.0,
        pitch=1.0,
        volume=1.0,
    )

    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.COMPLETED
    assert result.audio_file_path is not None
    assert Path(result.audio_file_path).is_file()
    assert result.cache_hit is False


async def test_second_identical_item_is_cache_hit(tts_service: TTSService) -> None:
    manager = QueueManager(max_size=10, max_history=10)
    processor = TTSQueueProcessor(tts_service, manager)
    worker = QueueWorker(manager, item_processor=processor)
    worker.start()

    try:
        first_item = await manager.enqueue("Teks yang sama", QueuePriority.NORMAL, voice="v1")
        await _wait_until(lambda: manager._registry[first_item.id].status == QueueItemStatus.COMPLETED)

        second_item = await manager.enqueue("Teks yang sama", QueuePriority.NORMAL, voice="v1")
        await _wait_until(lambda: manager._registry[second_item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    first_result = await manager.get_item(first_item.id)
    second_result = await manager.get_item(second_item.id)

    assert first_result.cache_hit is False
    assert second_result.cache_hit is True
    assert first_result.audio_file_path == second_result.audio_file_path


async def test_enqueue_without_tts_params_uses_defaults(tts_service: TTSService) -> None:
    """Memastikan backward-compatibility: enqueue(text, priority) tanpa kwargs TTS tetap berfungsi (kontrak Phase 2)."""
    manager = QueueManager(max_size=10, max_history=10)
    item = await manager.enqueue("Tanpa parameter TTS eksplisit", QueuePriority.NORMAL)

    assert item.voice == "default"
    assert item.speed == 1.0
    assert item.pitch == 1.0
    assert item.volume == 1.0
    assert item.audio_file_path is None
    assert item.cache_hit is None
