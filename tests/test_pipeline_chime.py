"""Test untuk fitur Chime (opsional) pada AnnouncementPipelineProcessor.

Chime = file audio statis (mis. ``sounds/chime.wav``) yang diputar SEKALI
SEBELUM pengumuman utama. Bersifat OPSIONAL & best-effort (lihat
``queueing/pipeline_processor.py``):

- Tanpa ``chime_file`` -> perilaku identik seperti sebelum fitur ini ada
  (hanya pengumuman yang diputar).
- File chime hilang / resolver tidak tersedia / playback chime gagal ->
  pengumuman utama TETAP diputar (item tidak menjadi FAILED).

Test di file ini memakai ``FakePlaybackManager`` (double ringan, tidak
butuh hardware audio) dan ``AudioAssetResolver`` sungguhan dengan
direktori ``sounds`` di tmp (pola sama seperti ``test_speak_announcement_type_api.py``).
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.announcement.source_processor import AnnouncementSourceProcessor
from announcement_server.core.config import AnnouncementConfig
from announcement_server.core.exceptions import AudioFileNotFoundError
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import AnnouncementType, QueueItem, QueuePriority
from announcement_server.queueing.pipeline_processor import AnnouncementPipelineProcessor


def _write_wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(22050)
        writer.writeframes(b"\x00\x00" * 100)
    return path


class FakePlaybackManager:
    """Double untuk PlaybackManager: mencatat pemanggilan tanpa hardware audio sungguhan."""

    def __init__(self, *, raise_on_path_substring: str | None = None) -> None:
        self.play_calls: list[str] = []
        self.play_attempts: list[str] = []
        self.wait_calls: int = 0
        self._raise_on_path_substring = raise_on_path_substring

    async def play(self, file_path: str) -> None:
        self.play_attempts.append(file_path)
        if self._raise_on_path_substring is not None and self._raise_on_path_substring in file_path:
            raise AudioFileNotFoundError(f"File tidak ditemukan: {file_path}")
        self.play_calls.append(file_path)

    async def wait_until_finished(self) -> None:
        self.wait_calls += 1


class StubTTSProcessor:
    """Double untuk TTSQueueProcessor: menulis file WAV dan meng-update audio_file_path item."""

    def __init__(self, manager: QueueManager, output_dir: Path) -> None:
        self._manager = manager
        self._output_dir = output_dir
        self.calls: list[QueueItem] = []

    async def __call__(self, item: QueueItem) -> None:
        self.calls.append(item)
        target = _write_wav(self._output_dir / f"{item.id}.wav")
        await self._manager.update_tts_result(item.id, audio_file_path=str(target), cache_hit=False)


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


@pytest.fixture()
def output_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "out"
    directory.mkdir()
    return directory


async def _build_pipeline(
    manager: QueueManager,
    playback: FakePlaybackManager,
    output_dir: Path,
    asset_resolver: AudioAssetResolver | None,
) -> AnnouncementPipelineProcessor:
    tts_processor = StubTTSProcessor(manager, output_dir)
    pipeline = AnnouncementPipelineProcessor(
        tts_processor,
        manager,
        playback,
        post_playback_delay_seconds=0.0,
        asset_resolver=asset_resolver,
    )
    return pipeline


async def test_pipeline_plays_chime_before_announcement(
    sounds_dir: Path, asset_resolver: AudioAssetResolver, output_dir: Path
) -> None:
    """Chime diputar SEKALI SEBELUM pengumuman utama (urutan play_calls = [chime, pengumuman])."""
    chime_path = _write_wav(sounds_dir / "chime.wav")

    manager = QueueManager(max_size=10, max_history=10)
    playback = FakePlaybackManager()
    pipeline = await _build_pipeline(manager, playback, output_dir, asset_resolver)

    await manager.enqueue("Halo dengan chime", QueuePriority.NORMAL, voice="v1", chime_file="chime.wav")
    processing_item = await manager.dequeue_for_processing()
    assert processing_item is not None
    await pipeline(processing_item)

    announcement_path = output_dir / f"{processing_item.id}.wav"
    assert playback.play_calls == [str(chime_path), str(announcement_path)]
    assert playback.wait_calls == 2


async def test_pipeline_without_chime_plays_only_announcement(
    asset_resolver: AudioAssetResolver, output_dir: Path
) -> None:
    """Regresi: tanpa `chime_file`, perilaku identik seperti sebelum fitur chime ada."""
    manager = QueueManager(max_size=10, max_history=10)
    playback = FakePlaybackManager()
    pipeline = await _build_pipeline(manager, playback, output_dir, asset_resolver)

    await manager.enqueue("Tanpa chime", QueuePriority.NORMAL, voice="v1")
    processing_item = await manager.dequeue_for_processing()
    assert processing_item is not None
    await pipeline(processing_item)

    assert playback.play_calls == [str(output_dir / f"{processing_item.id}.wav")]
    assert playback.wait_calls == 1


async def test_pipeline_continues_when_chime_file_missing(
    asset_resolver: AudioAssetResolver, output_dir: Path
) -> None:
    """Best-effort: file chime tidak ditemukan -> pengumuman utama TETAP diputar."""
    manager = QueueManager(max_size=10, max_history=10)
    playback = FakePlaybackManager()
    pipeline = await _build_pipeline(manager, playback, output_dir, asset_resolver)

    await manager.enqueue(
        "Chime hilang", QueuePriority.NORMAL, voice="v1", chime_file="tidak-ada.wav"
    )
    processing_item = await manager.dequeue_for_processing()
    assert processing_item is not None
    await pipeline(processing_item)

    assert playback.play_calls == [str(output_dir / f"{processing_item.id}.wav")]
    assert playback.wait_calls == 1


async def test_pipeline_skips_chime_when_no_asset_resolver(output_dir: Path) -> None:
    """Jika pipeline tidak memiliki AudioAssetResolver, chime dilewati (bukan error)."""
    manager = QueueManager(max_size=10, max_history=10)
    playback = FakePlaybackManager()
    pipeline = await _build_pipeline(manager, playback, output_dir, asset_resolver=None)

    await manager.enqueue("Tanpa resolver", QueuePriority.NORMAL, voice="v1", chime_file="chime.wav")
    processing_item = await manager.dequeue_for_processing()
    assert processing_item is not None
    await pipeline(processing_item)

    assert playback.play_calls == [str(output_dir / f"{processing_item.id}.wav")]
    assert playback.wait_calls == 1


async def test_pipeline_chime_playback_failure_does_not_fail_announcement(
    sounds_dir: Path, asset_resolver: AudioAssetResolver, output_dir: Path
) -> None:
    """Playback chime gagal (mis. device bermasalah saat memutar chime) -> pengumuman TETAP diputar."""
    chime_path = _write_wav(sounds_dir / "chime.wav")

    manager = QueueManager(max_size=10, max_history=10)
    # Substring `chime.wav` (bukan `chime`): nama direktori tmp pytest mengandung
    # nama test ("test_pipeline_chime_..."), jadi `"chime"` ikut match path
    # pengumuman utama dan membuatnya ikut "gagal" (play_calls jadi kosong).
    playback = FakePlaybackManager(raise_on_path_substring="chime.wav")
    pipeline = await _build_pipeline(manager, playback, output_dir, asset_resolver)

    await manager.enqueue("Chime gagal putar", QueuePriority.NORMAL, voice="v1", chime_file="chime.wav")
    processing_item = await manager.dequeue_for_processing()
    assert processing_item is not None
    await pipeline(processing_item)

    # play chime DICOBA (tercatat di play_attempts) lalu gagal; pengumuman tetap diputar.
    assert playback.play_attempts == [str(chime_path), str(output_dir / f"{processing_item.id}.wav")]
    assert playback.play_calls == [str(output_dir / f"{processing_item.id}.wav")]
    # wait_until_finished hanya dipanggil setelah play() BERHASIL (lihat _play_audio_file)
    # -- karena chime gagal diputar, hanya pengumuman yang ditunggu (1x).
    assert playback.wait_calls == 1


async def test_pipeline_plays_chime_for_audio_type_item(
    sounds_dir: Path, asset_resolver: AudioAssetResolver, output_dir: Path
) -> None:
    """Chime juga berlaku untuk item `type='audio'` — lewat susunan produksi identik
    ZoneManager.create_zone: AnnouncementSourceProcessor -> AnnouncementPipelineProcessor."""
    chime_path = _write_wav(sounds_dir / "chime.wav")
    bell_path = _write_wav(sounds_dir / "bell.wav")

    manager = QueueManager(max_size=10, max_history=10)
    tts_processor = StubTTSProcessor(manager, output_dir)
    source_processor = AnnouncementSourceProcessor(tts_processor, asset_resolver, manager)
    playback = FakePlaybackManager()
    pipeline = AnnouncementPipelineProcessor(
        source_processor,
        manager,
        playback,
        post_playback_delay_seconds=0.0,
        asset_resolver=asset_resolver,
    )

    await manager.enqueue(
        "[audio] bell.wav",
        QueuePriority.NORMAL,
        announcement_type=AnnouncementType.AUDIO,
        source_file="bell.wav",
        chime_file="chime.wav",
    )
    processing_item = await manager.dequeue_for_processing()
    assert processing_item is not None
    await pipeline(processing_item)

    assert playback.play_calls == [str(chime_path), str(bell_path)]
    assert playback.wait_calls == 2
