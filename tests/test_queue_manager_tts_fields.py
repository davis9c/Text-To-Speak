"""Unit test untuk field & method TTS yang ditambahkan ke QueueManager pada Phase 3."""

from __future__ import annotations

import pytest

from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueuePriority


@pytest.fixture()
def manager() -> QueueManager:
    return QueueManager(max_size=10, max_history=10)


async def test_enqueue_stores_tts_params(manager: QueueManager) -> None:
    item = await manager.enqueue(
        "Halo",
        QueuePriority.HIGH,
        voice="en_US-lessac-medium",
        speed=1.2,
        pitch=0.9,
        volume=1.1,
    )
    assert item.voice == "en_US-lessac-medium"
    assert item.speed == 1.2
    assert item.pitch == 0.9
    assert item.volume == 1.1
    assert item.audio_file_path is None
    assert item.cache_hit is None


async def test_update_tts_result_sets_audio_fields_without_changing_status(manager: QueueManager) -> None:
    item = await manager.enqueue("Halo", QueuePriority.NORMAL)
    await manager.dequeue_for_processing()  # status -> PROCESSING

    await manager.update_tts_result(item.id, audio_file_path="/cache/audio/abc123.wav", cache_hit=False)

    updated = await manager.get_item(item.id)
    assert updated.audio_file_path == "/cache/audio/abc123.wav"
    assert updated.cache_hit is False
    assert updated.status.value == "processing"  # status TIDAK berubah oleh update_tts_result


async def test_update_tts_result_on_unknown_id_does_not_raise(manager: QueueManager) -> None:
    import uuid

    # Tidak melempar exception — item mungkin sudah dipangkas dari history; ini bukan skenario fatal.
    await manager.update_tts_result(uuid.uuid4(), audio_file_path="/x.wav", cache_hit=True)
