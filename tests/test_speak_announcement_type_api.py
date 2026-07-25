"""Test untuk Phase 7 (Announcement Engine) — `type`/`file` pada SpeakRequest.

Dua kelompok test:

1. Validasi request/response HTTP lewat `POST /speak` (memakai `client` dari
   conftest.py — app sungguhan; TIDAK butuh file audio benar-benar ada
   karena `/speak` hanya meng-enqueue, resolusi terjadi belakangan secara
   asinkron oleh worker, jadi aman diverifikasi lewat response 201/422 saja).

2. End-to-end pipeline (`QueueManager` + `AnnouncementSourceProcessor` +
   `AnnouncementPipelineProcessor` + `QueueWorker` sungguhan, disusun
   PERSIS seperti `ZoneManager.create_zone` di production) yang
   memverifikasi item bertipe `audio` BENAR-BENAR selesai diproses.
   SENGAJA tidak lewat HTTP/TestClient untuk bagian ini — TestClient
   menjalankan aplikasi ASGI lewat thread/loop portal internalnya sendiri,
   terpisah dari loop test; mencampur QueueWorker (dibuat di loop test)
   dengan akses lewat portal TestClient berisiko `asyncio.Lock` "bound to
   a different event loop". Menjalankan seluruh pipeline langsung di dalam
   satu fungsi test `async def` (satu loop yang sama) menghindari isu ini
   sepenuhnya sekaligus tetap memvalidasi wiring produksi yang identik.
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.announcement.source_processor import AnnouncementSourceProcessor
from announcement_server.core.config import AnnouncementConfig
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import AnnouncementType, QueueItemStatus, QueuePriority
from announcement_server.queueing.pipeline_processor import AnnouncementPipelineProcessor
from announcement_server.queueing.worker import QueueWorker


# --- Kelompok 1: validasi request/response (app sungguhan dari conftest.client) ---


def test_speak_default_type_is_tts_backward_compat(client: TestClient) -> None:
    """Payload lama (tanpa `type`) HARUS tetap berperilaku type='tts' (Phase 1-6)."""
    response = client.post("/speak", json={"text": "Halo dunia"})
    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "tts"
    assert body["text"] == "Halo dunia"
    assert body["file"] is None


def test_speak_type_tts_missing_text_returns_422(client: TestClient) -> None:
    response = client.post("/speak", json={"type": "tts"})
    assert response.status_code == 422


def test_speak_type_tts_empty_text_returns_422(client: TestClient) -> None:
    response = client.post("/speak", json={"type": "tts", "text": "   "})
    assert response.status_code == 422


def test_speak_type_audio_missing_file_returns_422(client: TestClient) -> None:
    response = client.post("/speak", json={"type": "audio"})
    assert response.status_code == 422


def test_speak_type_audio_valid_returns_201_with_auto_text(client: TestClient) -> None:
    response = client.post("/speak", json={"type": "audio", "file": "sounds/bell.wav", "priority": "high"})
    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "audio"
    assert body["file"] == "sounds/bell.wav"
    assert body["text"] == "[audio] sounds/bell.wav"
    assert body["status"] == "pending"


def test_speak_type_audio_with_explicit_text_keeps_it(client: TestClient) -> None:
    response = client.post("/speak", json={"type": "audio", "file": "sounds/bell.wav", "text": "Bel tanda masuk"})
    assert response.status_code == 201
    assert response.json()["text"] == "Bel tanda masuk"


# --- Kelompok 2: end-to-end pipeline sungguhan (tanpa HTTP, satu event loop) ---


@pytest.fixture()
def sounds_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "sounds"
    directory.mkdir()
    return directory


@pytest.fixture()
def asset_resolver(tmp_path: Path, sounds_dir: Path) -> AudioAssetResolver:
    config = AnnouncementConfig(
        sounds_dir=str(sounds_dir),
        converted_cache_dir=str(tmp_path / "cache_announcement"),
    )
    return AudioAssetResolver(config)


class RecordingTTSProcessor:
    """Double untuk TTSQueueProcessor — item bertipe TTS TIDAK dipakai oleh test di sini,
    disediakan hanya karena AnnouncementSourceProcessor selalu butuh satu."""

    def __init__(self) -> None:
        self.received_items: list = []

    async def __call__(self, item) -> None:  # noqa: ANN001 - double sederhana, tipe tidak krusial
        self.received_items.append(item)


async def _wait_until_final(manager: QueueManager, item_id, timeout: float = 2.0) -> None:
    elapsed = 0.0
    interval = 0.01
    while elapsed < timeout:
        item = await manager.get_item(item_id)
        if item.status in (QueueItemStatus.COMPLETED, QueueItemStatus.FAILED):
            return
        await asyncio.sleep(interval)
        elapsed += interval
    raise AssertionError("Timeout menunggu item selesai diproses oleh QueueWorker.")


async def test_worker_completes_audio_item_end_to_end(asset_resolver: AudioAssetResolver, sounds_dir: Path) -> None:
    """Susunan identik dengan `ZoneManager.create_zone`: QueueManager -> AnnouncementSourceProcessor
    -> AnnouncementPipelineProcessor -> QueueWorker, dijalankan langsung (tanpa Playback/HTTP)."""
    wav_path = sounds_dir / "bell.wav"
    with wave.open(str(wav_path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(22050)
        writer.writeframes(b"\x00\x00" * 100)

    manager = QueueManager(max_size=10, max_history=10)
    source_processor = AnnouncementSourceProcessor(RecordingTTSProcessor(), asset_resolver, manager)
    pipeline = AnnouncementPipelineProcessor(source_processor, manager, playback_manager=None, post_playback_delay_seconds=0.0)
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue(
        "[audio] bell.wav",
        QueuePriority.NORMAL,
        announcement_type=AnnouncementType.AUDIO,
        source_file="bell.wav",
    )
    worker.start()
    try:
        await _wait_until_final(manager, item.id)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.COMPLETED
    assert result.audio_file_path == str(wav_path)
    assert result.cache_hit is True


async def test_worker_marks_audio_item_failed_when_file_missing(asset_resolver: AudioAssetResolver) -> None:
    manager = QueueManager(max_size=10, max_history=10)
    source_processor = AnnouncementSourceProcessor(RecordingTTSProcessor(), asset_resolver, manager)
    pipeline = AnnouncementPipelineProcessor(source_processor, manager, playback_manager=None, post_playback_delay_seconds=0.0)
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue(
        "[audio] tidak-ada.wav",
        QueuePriority.NORMAL,
        announcement_type=AnnouncementType.AUDIO,
        source_file="tidak-ada.wav",
    )
    worker.start()
    try:
        await _wait_until_final(manager, item.id)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.FAILED
    assert result.error_message is not None


async def test_worker_still_processes_tts_item_when_mixed_with_audio_items(
    asset_resolver: AudioAssetResolver, sounds_dir: Path
) -> None:
    """Regresi: satu QueueWorker/pipeline yang sama harus tetap bisa memproses item TTS
    berdampingan dengan item audio (dispatcher tidak salah rute)."""
    wav_path = sounds_dir / "bell.wav"
    with wave.open(str(wav_path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(22050)
        writer.writeframes(b"\x00\x00" * 100)

    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = RecordingTTSProcessor()
    source_processor = AnnouncementSourceProcessor(tts_processor, asset_resolver, manager)
    pipeline = AnnouncementPipelineProcessor(source_processor, manager, playback_manager=None, post_playback_delay_seconds=0.0)
    worker = QueueWorker(manager, item_processor=pipeline)

    audio_item = await manager.enqueue(
        "[audio] bell.wav",
        QueuePriority.NORMAL,
        announcement_type=AnnouncementType.AUDIO,
        source_file="bell.wav",
    )
    tts_item = await manager.enqueue("Halo dunia", QueuePriority.NORMAL)  # default: type TTS (backward compat)

    worker.start()
    try:
        await _wait_until_final(manager, audio_item.id)
        # RecordingTTSProcessor tidak memanggil update_tts_result, jadi item TTS akan
        # "selesai" (mark_completed tetap dipanggil QueueWorker) walau audio_file_path
        # tetap None — cukup untuk membuktikan item benar-benar sampai ke tts_processor.
        await _wait_until_final(manager, tts_item.id)
    finally:
        await worker.stop()

    assert len(tts_processor.received_items) == 1
    assert tts_processor.received_items[0].id == tts_item.id
