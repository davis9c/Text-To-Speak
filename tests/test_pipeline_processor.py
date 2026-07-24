"""Test untuk AnnouncementPipelineProcessor (Phase 5): TTS + Playback + Delay disatukan.

Memakai FakeEngine (bukan Piper asli, sama seperti test_queue_tts_integration.py)
dan FakePlaybackManager (double ringan untuk PlaybackManager, tidak butuh
hardware audio) supaya test cepat & deterministik.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import AudioFileNotFoundError
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueueItem, QueueItemStatus, QueuePriority
from announcement_server.queueing.pipeline_processor import AnnouncementPipelineProcessor
from announcement_server.queueing.tts_processor import TTSQueueProcessor
from announcement_server.queueing.worker import QueueWorker
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService


class FakeEngine(TTSEngine):
    """Engine TTS palsu: menghasilkan WAV valid tanpa memanggil Piper asli."""

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


class FakePlaybackManager:
    """Double untuk PlaybackManager: mencatat pemanggilan tanpa hardware audio sungguhan."""

    def __init__(self, *, raise_on_play: Exception | None = None) -> None:
        self.play_calls: list[str] = []
        self.wait_calls: int = 0
        self._raise_on_play = raise_on_play

    async def play(self, file_path: str) -> None:
        if self._raise_on_play is not None:
            raise self._raise_on_play
        self.play_calls.append(file_path)

    async def wait_until_finished(self) -> None:
        self.wait_calls += 1


@pytest.fixture(autouse=True)
def register_fake_engine():
    EngineFactory.register("fake_pipeline_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_pipeline_engine"]


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_pipeline_engine", cache_dir=str(tmp_path / "cache"))
    return TTSService(config)


async def _wait_until(condition, timeout: float = 2.0, interval: float = 0.01) -> None:
    elapsed = 0.0
    while not condition():
        if elapsed >= timeout:
            raise AssertionError("Timeout menunggu kondisi terpenuhi.")
        await asyncio.sleep(interval)
        elapsed += interval


async def test_pipeline_plays_audio_and_completes(tts_service: TTSService) -> None:
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    playback = FakePlaybackManager()
    pipeline = AnnouncementPipelineProcessor(tts_processor, manager, playback, post_playback_delay_seconds=0.0)
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue("Nomor antrean A001", QueuePriority.NORMAL, voice="v1")

    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.COMPLETED
    assert result.audio_file_path is not None
    assert playback.play_calls == [result.audio_file_path]
    assert playback.wait_calls == 1


async def test_pipeline_skips_playback_when_playback_manager_unavailable(tts_service: TTSService) -> None:
    """Playback bersifat opsional (Phase 4): jika PlaybackManager None (driver audio tidak
    terdeteksi), item TETAP COMPLETED — hanya tahap Playback yang dilewati."""
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    pipeline = AnnouncementPipelineProcessor(tts_processor, manager, None, post_playback_delay_seconds=0.0)
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue("Tanpa driver audio", QueuePriority.NORMAL, voice="v1")

    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.COMPLETED
    assert result.audio_file_path is not None


async def test_pipeline_marks_completed_even_when_playback_fails(tts_service: TTSService) -> None:
    """Kegagalan tahap Playback (mis. device dicabut/file hilang) TIDAK boleh menandai item
    FAILED, karena sintesis TTS-nya sendiri sudah berhasil (lihat rationale di
    pipeline_processor.py)."""
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    playback = FakePlaybackManager(raise_on_play=AudioFileNotFoundError("File hilang"))
    pipeline = AnnouncementPipelineProcessor(tts_processor, manager, playback, post_playback_delay_seconds=0.0)
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue("Playback gagal", QueuePriority.NORMAL, voice="v1")

    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.COMPLETED


async def test_pipeline_marks_failed_when_tts_stage_fails() -> None:
    """Kegagalan TAHAP TTS (bukan Playback) tetap FAILED — kontrak Phase 3 tidak berubah,
    dan tahap Playback tidak boleh dicoba sama sekali."""
    manager = QueueManager(max_size=10, max_history=10)

    async def failing_tts_processor(_item: QueueItem) -> None:
        raise RuntimeError("Simulasi Piper gagal")

    playback = FakePlaybackManager()
    pipeline = AnnouncementPipelineProcessor(
        failing_tts_processor, manager, playback, post_playback_delay_seconds=0.0
    )
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue("Akan gagal di tahap TTS", QueuePriority.NORMAL)

    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.FAILED)
    finally:
        await worker.stop()

    assert playback.play_calls == []
    assert playback.wait_calls == 0


async def test_pipeline_applies_post_playback_delay(tts_service: TTSService) -> None:
    """Tahap Delay (roadmap Phase 5) benar-benar menjeda sebelum __call__ selesai."""
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    playback = FakePlaybackManager()
    pipeline = AnnouncementPipelineProcessor(tts_processor, manager, playback, post_playback_delay_seconds=0.1)

    await manager.enqueue("Cek delay", QueuePriority.NORMAL, voice="v1")
    processing_item = await manager.dequeue_for_processing()
    assert processing_item is not None

    start = time.perf_counter()
    await pipeline(processing_item)
    elapsed = time.perf_counter() - start

    assert elapsed >= 0.1


async def test_pipeline_zero_delay_does_not_sleep(tts_service: TTSService) -> None:
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    playback = FakePlaybackManager()
    pipeline = AnnouncementPipelineProcessor(tts_processor, manager, playback, post_playback_delay_seconds=0.0)

    await manager.enqueue("Tanpa delay", QueuePriority.NORMAL, voice="v1")
    processing_item = await manager.dequeue_for_processing()
    assert processing_item is not None

    start = time.perf_counter()
    await pipeline(processing_item)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5
