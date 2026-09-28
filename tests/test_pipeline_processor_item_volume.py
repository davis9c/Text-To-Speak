"""Test untuk ``volume`` per-item pada pipeline playback.

LATAR BELAKANG — bug yang diperbaiki:

Field ``volume`` dari request (``SpeakRequest.volume``) punya titik penerapan
yang BERBEDA-BEDA tergantung jenis audio, sehingga hasilnya tidak konsisten:

- ``type='tts'``  -> sudah dipanggang ke file cache TTS (``TTSService``),
  jadi pipeline TIDAK boleh menerapkannya lagi.
- chime           -> tidak pernah melewati cache TTS, sehingga ``volume``
  TIDAK pernah diterapkan sama sekali (chime hanya kena gain zone).
- ``type='audio'``-> file statis dipakai apa adanya, ``volume`` juga
  TIDAK pernah diterapkan (diam-diam diabaikan).

Test di sini mengunci bahwa ``volume`` berlaku SERAGAT untuk ketiganya, dan
khususnya bahwa volume TTS TIDAK ter-kuadrat di pipeline.
"""

from __future__ import annotations

import asyncio
import io
import struct
import wave
from pathlib import Path

import pytest

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.announcement.source_processor import AnnouncementSourceProcessor
from announcement_server.core.config import AnnouncementConfig, TTSConfig
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import AnnouncementType, QueueItemStatus, QueuePriority
from announcement_server.queueing.pipeline_processor import AnnouncementPipelineProcessor
from announcement_server.queueing.tts_processor import TTSQueueProcessor
from announcement_server.queueing.worker import QueueWorker
from announcement_server.tts.audio_processor import AudioProcessor
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService

AMPLITUDE = 8000
N_FRAMES = 200


def _make_wav_bytes(n_frames: int = N_FRAMES, amplitude: int = AMPLITUDE) -> bytes:
    """WAV berisi amplitudo konstan NON-NOL (bukan silence) supaya perubahan volume
    benar-benar terlihat di byte audio."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(22050)
        writer.writeframes(struct.pack(f"<{n_frames}h", *([amplitude] * n_frames)))
    return buffer.getvalue()


class FakeEngine(TTSEngine):
    """Engine palsu: menghasilkan WAV dengan amplitudo konstan non-nol."""

    def __init__(self, config: TTSConfig) -> None:
        self.config = config

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        return _make_wav_bytes()


class RecordingPlaybackManager:
    """Double PlaybackManager yang menyimpan ISI file saat ``play()`` dipanggil —
    supaya test bisa memeriksa audio yang benar-benar diputar SEBELUM pipeline
    menghapus file sementara di tahap ``finally``."""

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
    EngineFactory.register("fake_item_volume_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_item_volume_engine"]


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    return TTSService(TTSConfig(engine="fake_item_volume_engine", cache_dir=str(tmp_path / "cache")))


@pytest.fixture()
def sounds_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "sounds"
    directory.mkdir()
    return directory


@pytest.fixture()
def asset_resolver(tmp_path: Path, sounds_dir: Path) -> AudioAssetResolver:
    return AudioAssetResolver(
        AnnouncementConfig(sounds_dir=str(sounds_dir), converted_cache_dir=str(tmp_path / "cache_announcement"))
    )


async def _run_item(
    tts_service: TTSService,
    asset_resolver: AudioAssetResolver,
    tmp_path: Path,
    *,
    volume: float,
    zone_gain: float,
    chime_file: str | None = None,
    announcement_type: AnnouncementType = AnnouncementType.TTS,
    source_file: str | None = None,
) -> tuple[RecordingPlaybackManager, QueueItemStatus, str | None]:
    """Jalankan satu item sampai selesai; kembalikan rekaman playback + path audio cache."""
    manager = QueueManager(max_size=10, max_history=10)
    playback = RecordingPlaybackManager()
    tts_processor = TTSQueueProcessor(tts_service, manager)
    source_processor = AnnouncementSourceProcessor(tts_processor, asset_resolver, manager)
    pipeline = AnnouncementPipelineProcessor(
        source_processor,
        manager,
        playback,
        post_playback_delay_seconds=0.0,
        volume_gain=zone_gain,
        scaled_audio_dir=str(tmp_path / "zone_audio"),
        asset_resolver=asset_resolver,
    )
    worker = QueueWorker(manager, item_processor=pipeline)

    item = await manager.enqueue(
        "Halo",
        QueuePriority.NORMAL,
        volume=volume,
        announcement_type=announcement_type,
        source_file=source_file,
        chime_file=chime_file,
    )
    worker.start()
    try:
        elapsed = 0.0
        while manager._registry[item.id].status != QueueItemStatus.COMPLETED and elapsed < 3.0:
            await asyncio.sleep(0.01)
            elapsed += 0.01
    finally:
        await worker.stop()

    return playback, manager._registry[item.id].status, manager._registry[item.id].audio_file_path


# --- TTS: volume SUDAH di-cache, pipeline tidak boleh menerapkannya lagi -----


async def test_tts_volume_is_not_applied_twice(tts_service: TTSService, asset_resolver: AudioAssetResolver, tmp_path: Path) -> None:
    """Guard terhadap volume ter-kuadrat.

    `volume=0.5` untuk item TTS: nilainya sudah dipanggang ke file cache TTS,
    jadi pipeline harus memutar file itu APA ADANYA (tidak membuat file
    sementara). Kalau pipeline ikut menerapkannya lagi, amplitudo akhir jadi
    0.25 dari yang klien minta.
    """
    playback, status, audio_path = await _run_item(
        tts_service, asset_resolver, tmp_path, volume=0.5, zone_gain=1.0
    )

    assert status == QueueItemStatus.COMPLETED
    assert audio_path is not None
    # Tidak ada file sementara sama sekali -> gain di playback = 1.0.
    assert playback.play_calls == [audio_path]
    # Audio yang diputar persis hasil cache (volume 0.5 TERDAKALI, bukan 0.25).
    assert playback.played_bytes[0] == Path(audio_path).read_bytes()
    assert playback.played_bytes[0] == AudioProcessor().apply_volume(_make_wav_bytes(), 0.5)
    assert playback.played_bytes[0] != AudioProcessor().apply_volume(_make_wav_bytes(), 0.25)


async def test_tts_volume_is_still_combined_with_zone_gain(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, tmp_path: Path
) -> None:
    """Untuk TTS, gain ZONE tetap diterapkan di playback (volume item sudah di-cache),
    jadi gain total di playback hanya zone_gain."""
    playback, status, audio_path = await _run_item(
        tts_service, asset_resolver, tmp_path, volume=0.5, zone_gain=0.5
    )

    assert status == QueueItemStatus.COMPLETED
    assert audio_path is not None
    assert playback.play_calls[0] != audio_path  # zone gain != 1.0 -> pakai file sementara
    # File cache = volume 0.5, lalu di-scaled lagi 0.5 oleh zone gain.
    expected = AudioProcessor().apply_volume(Path(audio_path).read_bytes(), 0.5)
    assert playback.played_bytes[0] == expected


# --- Chime: volume SEBELUMNYA tidak pernah diterapkan --------------------------


async def test_chime_now_honours_item_volume(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, sounds_dir: Path, tmp_path: Path
) -> None:
    """Chime harus ikut dikenai `volume` dari request.

    Sebelumnya chime HANYA kena gain zone, sehingga `volume=0.5` +
    `zone_gain=1.0` tidak berefek apa-apa pada chime.
    """
    chime_source = sounds_dir / "chime.wav"
    chime_source.write_bytes(_make_wav_bytes())

    playback, status, audio_path = await _run_item(
        tts_service, asset_resolver, tmp_path, volume=0.5, zone_gain=1.0, chime_file="chime.wav"
    )

    assert status == QueueItemStatus.COMPLETED
    assert len(playback.play_calls) == 2  # chime lalu pengumuman

    # Chime: 8000 -> 4000 (volume 0.5 dari request).
    chime_played = playback.played_bytes[0]
    assert chime_played == AudioProcessor().apply_volume(_make_wav_bytes(), 0.5)

    # Pengumuman utama: `volume=0.5` sudah dipanggang ke file cache TTS, dan
    # zone_gain=1.0 -> pipeline memutar file cache itu apa adanya (tanpa
    # terapkan 0.5 kedua kali).
    assert audio_path is not None
    assert playback.played_bytes[1] == Path(audio_path).read_bytes()
    assert playback.played_bytes[1] == AudioProcessor().apply_volume(_make_wav_bytes(), 0.5)


async def test_chime_multiplies_item_volume_with_zone_gain(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, sounds_dir: Path, tmp_path: Path
) -> None:
    """Chime dan gain zone adalah dua gain independen -> dikalikan (0.5 x 0.5 = 0.25)."""
    (sounds_dir / "chime.wav").write_bytes(_make_wav_bytes())

    playback, status, _ = await _run_item(
        tts_service, asset_resolver, tmp_path, volume=0.5, zone_gain=0.5, chime_file="chime.wav"
    )

    assert status == QueueItemStatus.COMPLETED
    assert playback.played_bytes[0] == AudioProcessor().apply_volume(_make_wav_bytes(), 0.25)


async def test_chime_and_announcement_use_separate_temp_files(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, sounds_dir: Path, tmp_path: Path
) -> None:
    """Chime dan pengumuman utama bisa sama-sama butuh file sementara pada satu item.
    Keduanya harus punya file sendiri (nama berbasis label), tidak berebut path sama."""
    (sounds_dir / "chime.wav").write_bytes(_make_wav_bytes())
    scaled_dir = tmp_path / "zone_audio"

    playback, status, _ = await _run_item(
        tts_service, asset_resolver, tmp_path, volume=0.5, zone_gain=0.5, chime_file="chime.wav"
    )

    assert status == QueueItemStatus.COMPLETED
    chime_path, announcement_path = playback.play_calls
    assert chime_path != announcement_path
    assert chime_path.startswith(str(scaled_dir))
    assert announcement_path.startswith(str(scaled_dir))
    assert Path(chime_path).name.endswith("_chime.wav")
    assert Path(announcement_path).name.endswith("_pengumuman.wav")


# --- type='audio': volume SEBELUMNYA diam-diam diabaikan --------------------


async def test_static_audio_file_honours_item_volume(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, sounds_dir: Path, tmp_path: Path
) -> None:
    """File statis `type='audio'` harus ikut dikenai `volume` (sebelumnya diabaikan)."""
    (sounds_dir / "bell.wav").write_bytes(_make_wav_bytes())

    playback, status, audio_path = await _run_item(
        tts_service,
        asset_resolver,
        tmp_path,
        volume=0.5,
        zone_gain=1.0,
        announcement_type=AnnouncementType.AUDIO,
        source_file="bell.wav",
    )

    assert status == QueueItemStatus.COMPLETED
    assert audio_path is not None
    assert playback.play_calls[0] != audio_path  # volume != 1.0 -> file sementara
    assert playback.played_bytes[0] == AudioProcessor().apply_volume(_make_wav_bytes(), 0.5)
    # File sumber TIDAK berubah (dipakai bersama & boleh dipakai ulang tanpa gain).
    assert (sounds_dir / "bell.wav").read_bytes() == _make_wav_bytes()


async def test_static_audio_multiplies_item_volume_with_zone_gain(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, sounds_dir: Path, tmp_path: Path
) -> None:
    (sounds_dir / "bell.wav").write_bytes(_make_wav_bytes())

    playback, status, _ = await _run_item(
        tts_service,
        asset_resolver,
        tmp_path,
        volume=0.5,
        zone_gain=0.5,
        announcement_type=AnnouncementType.AUDIO,
        source_file="bell.wav",
    )

    assert status == QueueItemStatus.COMPLETED
    assert playback.played_bytes[0] == AudioProcessor().apply_volume(_make_wav_bytes(), 0.25)


# --- Edge case: volume 0.0 (bisu) & 1.0 (tidak ada gain sama sekali) ---------


async def test_zero_volume_silences_chime_and_audio(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, sounds_dir: Path, tmp_path: Path
) -> None:
    """`volume=0.0` (bisu) harus benar-benar membuat diam untuk chime & file statis."""
    (sounds_dir / "chime.wav").write_bytes(_make_wav_bytes())
    (sounds_dir / "bell.wav").write_bytes(_make_wav_bytes())

    playback, status, _ = await _run_item(
        tts_service,
        asset_resolver,
        tmp_path,
        volume=0.0,
        zone_gain=1.0,
        chime_file="chime.wav",
        announcement_type=AnnouncementType.AUDIO,
        source_file="bell.wav",
    )

    assert status == QueueItemStatus.COMPLETED
    assert len(playback.play_calls) == 2
    for played in playback.played_bytes:
        # Amplitudo nol: tidak ada lagi sample non-nol di audio yang diputar.
        assert max(abs(v) for v in struct.unpack(f"<{N_FRAMES}h", played[-N_FRAMES * 2 :])) == 0


async def test_unit_volumes_play_original_files_without_temp_copies(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, sounds_dir: Path, tmp_path: Path
) -> None:
    """volume=1.0 + zone_gain=1.0 -> tidak ada file sementara untuk chime maupun statis."""
    (sounds_dir / "chime.wav").write_bytes(_make_wav_bytes())
    (sounds_dir / "bell.wav").write_bytes(_make_wav_bytes())

    playback, status, audio_path = await _run_item(
        tts_service,
        asset_resolver,
        tmp_path,
        volume=1.0,
        zone_gain=1.0,
        chime_file="chime.wav",
        announcement_type=AnnouncementType.AUDIO,
        source_file="bell.wav",
    )

    assert status == QueueItemStatus.COMPLETED
    assert playback.play_calls == [str(sounds_dir / "chime.wav"), audio_path]
