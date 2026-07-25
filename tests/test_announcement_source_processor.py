"""Unit test untuk AnnouncementSourceProcessor (Phase 7) — dispatcher TTS vs Audio Asset."""

from __future__ import annotations

import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

import pytest

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.announcement.source_processor import AnnouncementSourceProcessor
from announcement_server.core.config import AnnouncementConfig
from announcement_server.core.exceptions import AudioAssetNotFoundError
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import AnnouncementType, QueueItem, QueueItemStatus, QueuePriority


class RecordingTTSProcessor:
    """Double untuk TTSQueueProcessor: hanya mencatat item yang diterima."""

    def __init__(self) -> None:
        self.received_items: list[QueueItem] = []

    async def __call__(self, item: QueueItem) -> None:
        self.received_items.append(item)


def _make_item(*, announcement_type: AnnouncementType, source_file: str | None, text: str = "") -> QueueItem:
    now = datetime.now(timezone.utc)
    return QueueItem(
        id=uuid.uuid4(),
        text=text,
        priority=QueuePriority.NORMAL,
        status=QueueItemStatus.PROCESSING,
        created_at=now,
        updated_at=now,
        announcement_type=announcement_type,
        source_file=source_file,
    )


@pytest.fixture()
def sounds_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "sounds"
    directory.mkdir()
    return directory


@pytest.fixture()
def asset_resolver(tmp_path: Path, sounds_dir: Path) -> AudioAssetResolver:
    config = AnnouncementConfig(
        sounds_dir=str(sounds_dir),
        converted_cache_dir=str(tmp_path / "cache" / "announcement_audio"),
    )
    return AudioAssetResolver(config)


@pytest.fixture()
def queue_manager() -> QueueManager:
    return QueueManager(max_size=10, max_history=10)


async def test_tts_type_item_is_dispatched_to_tts_processor(
    asset_resolver: AudioAssetResolver, queue_manager: QueueManager
) -> None:
    tts_processor = RecordingTTSProcessor()
    processor = AnnouncementSourceProcessor(tts_processor, asset_resolver, queue_manager)

    item = _make_item(announcement_type=AnnouncementType.TTS, source_file=None, text="Halo dunia")
    await processor(item)

    assert tts_processor.received_items == [item]


async def test_audio_type_item_is_resolved_and_not_sent_to_tts_processor(
    asset_resolver: AudioAssetResolver, queue_manager: QueueManager, sounds_dir: Path
) -> None:
    wav_path = sounds_dir / "bell.wav"
    with wave.open(str(wav_path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(22050)
        writer.writeframes(b"\x00\x00" * 50)

    tts_processor = RecordingTTSProcessor()
    processor = AnnouncementSourceProcessor(tts_processor, asset_resolver, queue_manager)

    # Item harus terdaftar di registry QueueManager supaya update_tts_result benar-benar tersimpan.
    enqueued = await queue_manager.enqueue(
        "[audio] bell.wav",
        QueuePriority.NORMAL,
        announcement_type=AnnouncementType.AUDIO,
        source_file="bell.wav",
    )
    dequeued = await queue_manager.dequeue_for_processing()
    assert dequeued is not None

    await processor(dequeued)

    assert tts_processor.received_items == []
    result = await queue_manager.get_item(enqueued.id)
    assert result.audio_file_path == str(wav_path)
    assert result.cache_hit is True


async def test_audio_type_item_without_source_file_raises(
    asset_resolver: AudioAssetResolver, queue_manager: QueueManager
) -> None:
    processor = AnnouncementSourceProcessor(RecordingTTSProcessor(), asset_resolver, queue_manager)
    item = _make_item(announcement_type=AnnouncementType.AUDIO, source_file=None)

    with pytest.raises(AudioAssetNotFoundError):
        await processor(item)


async def test_audio_type_item_missing_file_propagates_error(
    asset_resolver: AudioAssetResolver, queue_manager: QueueManager
) -> None:
    processor = AnnouncementSourceProcessor(RecordingTTSProcessor(), asset_resolver, queue_manager)
    item = _make_item(announcement_type=AnnouncementType.AUDIO, source_file="tidak-ada.wav")

    with pytest.raises(AudioAssetNotFoundError):
        await processor(item)
