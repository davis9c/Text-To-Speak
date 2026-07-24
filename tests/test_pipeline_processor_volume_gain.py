"""Test untuk penambahan ``volume_gain`` (Phase 6) pada AnnouncementPipelineProcessor (Phase 5).

Melengkapi ``test_pipeline_processor.py`` (tidak diubah sama sekali) —
fokus test di sini KHUSUS pada perilaku baru: penerapan gain zone secara
on-the-fly saat playback, tanpa menyentuh file cache TTS aslinya.
"""

from __future__ import annotations

import asyncio
import io
import struct
import wave
from pathlib import Path

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueueItemStatus, QueuePriority
from announcement_server.queueing.pipeline_processor import AnnouncementPipelineProcessor
from announcement_server.queueing.tts_processor import TTSQueueProcessor
from announcement_server.queueing.worker import QueueWorker
from announcement_server.tts.audio_processor import AudioProcessor
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService


def _make_wav_bytes(n_frames: int = 200, amplitude: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(22050)
        writer.writeframes(struct.pack(f"<{n_frames}h", *([amplitude] * n_frames)))
    return buffer.getvalue()


class FakeEngine(TTSEngine):
    """Engine TTS palsu: menghasilkan WAV dengan amplitudo tidak-nol (bukan silence) supaya
    penerapan volume_gain benar-benar bisa diverifikasi lewat perubahan byte audio."""

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        return _make_wav_bytes()


class RecordingPlaybackManager:
    """Double untuk PlaybackManager: membaca & menyimpan ISI file (bukan hanya path) saat
    play() dipanggil — supaya test bisa memverifikasi audio yang benar-benar diputar sudah
    di-scale, SEBELUM pipeline membersihkan (menghapus) file sementara di tahap `finally`."""

    def __init__(self) -> None:
        self.play_calls: list[str] = []
        self.played_bytes: list[bytes] = []
        self.wait_calls = 0

    async def play(self, file_path: str) -> None:
        self.play_calls.append(file_path)
        self.played_bytes.append(Path(file_path).read_bytes())

    async def wait_until_finished(self) -> None:
        self.wait_calls += 1


@pytest.fixture(autouse=True)
def register_fake_engine():
    EngineFactory.register("fake_volume_gain_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_volume_gain_engine"]


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_volume_gain_engine", cache_dir=str(tmp_path / "cache"))
    return TTSService(config)


async def _wait_until(condition, timeout: float = 2.0, interval: float = 0.01) -> None:
    elapsed = 0.0
    while not condition():
        if elapsed >= timeout:
            raise AssertionError("Timeout menunggu kondisi terpenuhi.")
        await asyncio.sleep(interval)
        elapsed += interval


async def test_default_volume_gain_plays_original_cached_file_unchanged(tts_service: TTSService, tmp_path: Path) -> None:
    """gain=1.0 (default, dipakai zone 'main') HARUS berperilaku identik dengan Phase 5:
    tidak ada file sementara dibuat, file cache asli diputar apa adanya."""
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    playback = RecordingPlaybackManager()
    pipeline = AnnouncementPipelineProcessor(
        tts_processor, manager, playback, post_playback_delay_seconds=0.0, volume_gain=1.0
    )
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue("Volume default", QueuePriority.NORMAL, voice="v1")
    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert playback.play_calls == [result.audio_file_path]
    assert Path(result.audio_file_path).exists()  # file cache ASLI tetap ada, tidak dihapus


async def test_custom_volume_gain_scales_audio_and_uses_temp_file(tts_service: TTSService, tmp_path: Path) -> None:
    """gain != 1.0 HARUS memutar salinan yang sudah di-scale, BUKAN file cache asli, dan
    file cache asli TIDAK boleh berubah sama sekali (dipakai bersama seluruh zone)."""
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    playback = RecordingPlaybackManager()
    scaled_dir = tmp_path / "zone_audio" / "lobby"
    pipeline = AnnouncementPipelineProcessor(
        tts_processor,
        manager,
        playback,
        post_playback_delay_seconds=0.0,
        volume_gain=0.5,
        scaled_audio_dir=str(scaled_dir),
    )
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue("Volume setengah", QueuePriority.NORMAL, voice="v1")
    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    original_bytes = Path(result.audio_file_path).read_bytes()

    # File yang diputar BUKAN file cache asli (path berbeda, di direktori scaled_dir).
    assert playback.play_calls[0] != result.audio_file_path
    assert playback.play_calls[0].startswith(str(scaled_dir))

    # Isi audio yang diputar sudah benar-benar di-scale sesuai gain (dihitung ulang lewat
    # AudioProcessor.apply_volume yang sama, Phase 3, untuk dibandingkan).
    expected_bytes = AudioProcessor().apply_volume(original_bytes, 0.5)
    assert playback.played_bytes[0] == expected_bytes

    # File cache ASLI (Phase 3) sama sekali tidak berubah oleh gain zone.
    assert Path(result.audio_file_path).read_bytes() == original_bytes

    # File sementara yang sudah diputar dibersihkan (tidak menumpuk di disk).
    assert not (scaled_dir / f"{item.id}.wav").exists()


async def test_volume_gain_setter_is_applied_on_next_item(tts_service: TTSService, tmp_path: Path) -> None:
    """volume_gain bisa diubah setelah pipeline dibuat (dipakai ZoneManager.update_zone,
    Phase 6, saat PUT /zones/{name} mengubah volume) tanpa perlu membuat ulang pipeline."""
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    playback = RecordingPlaybackManager()
    pipeline = AnnouncementPipelineProcessor(
        tts_processor,
        manager,
        playback,
        post_playback_delay_seconds=0.0,
        volume_gain=1.0,
        scaled_audio_dir=str(tmp_path / "zone_audio"),
    )
    assert pipeline.volume_gain == 1.0

    pipeline.volume_gain = 0.25
    assert pipeline.volume_gain == 0.25

    worker = QueueWorker(manager, item_processor=pipeline)
    item = await manager.enqueue("Setelah gain diubah", QueuePriority.NORMAL, voice="v1")
    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert playback.play_calls[0] != result.audio_file_path  # gain baru tetap dipakai


async def test_volume_gain_failure_falls_back_to_original_file_gracefully(tts_service: TTSService, tmp_path: Path) -> None:
    """Jika penerapan gain gagal (mis. tidak bisa menulis file sementara), item TETAP
    COMPLETED dan diputar memakai file cache asli — konsisten dengan prinsip modul ini bahwa
    kegagalan di luar tahap TTS tidak boleh menggagalkan item yang TTS-nya sudah berhasil."""
    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = TTSQueueProcessor(tts_service, manager)
    playback = RecordingPlaybackManager()

    # scaled_audio_dir sengaja diarahkan ke path yang berupa FILE (bukan folder), sehingga
    # `.mkdir(parents=True, exist_ok=True)` di dalam pipeline pasti gagal (NotADirectoryError).
    blocking_file = tmp_path / "blocked"
    blocking_file.write_text("bukan folder")

    pipeline = AnnouncementPipelineProcessor(
        tts_processor,
        manager,
        playback,
        post_playback_delay_seconds=0.0,
        volume_gain=0.5,
        scaled_audio_dir=str(blocking_file / "zone_audio"),
    )
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue("Gain gagal diterapkan", QueuePriority.NORMAL, voice="v1")
    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.COMPLETED
    assert playback.play_calls == [result.audio_file_path]  # fallback ke file asli
