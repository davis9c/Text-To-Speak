"""Unit test untuk TTSService, memakai FakeEngine agar tidak bergantung pada Piper asli."""

from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import TTSEngineNotAvailableError
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService


def _make_tone_wav(rate: int = 22050, duration: float = 0.05, amplitude: int = 8000) -> bytes:
    """WAV berisi gelombang sinus (bukan silent) agar post-processing volume bisa diverifikasi."""
    n_samples = int(duration * rate)
    frames = bytearray()
    for i in range(n_samples):
        value = int(amplitude * math.sin(2 * math.pi * 440 * i / rate))
        frames += struct.pack("<h", value)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(bytes(frames))
    return buffer.getvalue()


class FakeEngine(TTSEngine):
    """Engine palsu yang menghitung berapa kali dipanggil, untuk verifikasi cache."""

    def __init__(self, config: TTSConfig) -> None:
        self.call_count = 0
        self.last_voice: str | None = None

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        self.call_count += 1
        self.last_voice = voice
        return _make_tone_wav()


@pytest.fixture(autouse=True)
def register_fake_engine():
    EngineFactory.register("fake_test_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_test_engine"]


@pytest.fixture()
def tts_config(tmp_path: Path) -> TTSConfig:
    return TTSConfig(engine="fake_test_engine", cache_dir=str(tmp_path / "cache"))


async def test_synthesize_cache_miss_then_hit(tts_config: TTSConfig) -> None:
    service = TTSService(tts_config)
    fake_engine: FakeEngine = service._engine_manager.get()  # type: ignore[assignment]

    first_result = await service.synthesize(text="Halo", voice="v1", speed=1.0, pitch=1.0, volume=1.0)
    assert first_result.cache_hit is False
    assert fake_engine.call_count == 1
    assert Path(first_result.audio_file_path).is_file()

    second_result = await service.synthesize(text="Halo", voice="v1", speed=1.0, pitch=1.0, volume=1.0)
    assert second_result.cache_hit is True
    assert fake_engine.call_count == 1  # engine TIDAK dipanggil lagi (cache hit)
    assert second_result.audio_file_path == first_result.audio_file_path


async def test_synthesize_different_params_bypasses_cache(tts_config: TTSConfig) -> None:
    service = TTSService(tts_config)
    fake_engine: FakeEngine = service._engine_manager.get()  # type: ignore[assignment]

    await service.synthesize(text="Halo", voice="v1", speed=1.0, pitch=1.0, volume=1.0)
    await service.synthesize(text="Halo", voice="v1", speed=1.5, pitch=1.0, volume=1.0)  # speed beda

    assert fake_engine.call_count == 2


async def test_synthesize_applies_volume_and_pitch_post_processing(tts_config: TTSConfig) -> None:
    service = TTSService(tts_config)

    normal_result = await service.synthesize(text="A", voice="v1", speed=1.0, pitch=1.0, volume=1.0)
    louder_result = await service.synthesize(text="A", voice="v1", speed=1.0, pitch=1.0, volume=1.8)

    normal_bytes = Path(normal_result.audio_file_path).read_bytes()
    louder_bytes = Path(louder_result.audio_file_path).read_bytes()
    # Volume berbeda -> hasil audio (setelah post-processing) berbeda -> cache key beda -> file beda.
    assert normal_result.audio_file_path != louder_result.audio_file_path
    assert normal_bytes != louder_bytes


# --- V2 Phase 2 — engine selection ------------------------------------------


async def test_synthesize_without_engine_uses_default_engine(tts_config: TTSConfig) -> None:
    """Backward compat V1: `engine` tidak diberikan (None) -> pakai engine default server."""
    service = TTSService(tts_config)
    fake_engine: FakeEngine = service._engine_manager.get()  # type: ignore[assignment]

    result = await service.synthesize(text="Halo", voice="v1", speed=1.0, pitch=1.0, volume=1.0)

    assert result.cache_hit is False
    assert fake_engine.call_count == 1


async def test_synthesize_with_explicit_matching_default_engine_name_hits_same_cache(tts_config: TTSConfig) -> None:
    """Memberikan `engine` yang namanya SAMA dengan default engine harus menghasilkan cache key
    yang identik dengan tidak memberikan `engine` sama sekali (V1 tidak pernah mengirim `engine`)."""
    service = TTSService(tts_config)

    without_engine = await service.synthesize(text="Halo", voice="v1", speed=1.0, pitch=1.0, volume=1.0)
    with_engine = await service.synthesize(
        text="Halo", voice="v1", speed=1.0, pitch=1.0, volume=1.0, engine="fake_test_engine"
    )

    assert with_engine.audio_file_path == without_engine.audio_file_path
    assert with_engine.cache_hit is True


async def test_synthesize_with_unknown_engine_raises_and_does_not_call_default_engine(tts_config: TTSConfig) -> None:
    """Engine tidak dikenal -> error, TIDAK fallback diam-diam ke engine default."""
    service = TTSService(tts_config)
    fake_engine: FakeEngine = service._engine_manager.get()  # type: ignore[assignment]

    with pytest.raises(TTSEngineNotAvailableError):
        await service.synthesize(text="Halo", voice="v1", speed=1.0, pitch=1.0, volume=1.0, engine="engine_tak_dikenal")

    assert fake_engine.call_count == 0


async def test_cache_key_distinguishes_between_engines(tmp_path: Path) -> None:
    """Cache HARUS tetap membedakan engine (Phase 1: cache key sudah mencakup `engine`) —
    dua engine berbeda untuk parameter lain yang identik tidak boleh saling bertabrakan di cache."""
    EngineFactory.register("second_fake_test_engine", FakeEngine)
    try:
        config = TTSConfig(engine="fake_test_engine", cache_dir=str(tmp_path / "cache"))
        service = TTSService(config)

        # Engine kedua belum "aktif" di TTSEngineManager (hanya default engine yang dibangun
        # eagerly, sesuai TTSEngineManager) — konstruksi manual di sini murni untuk memverifikasi
        # AudioCache.compute_key() sendiri tetap membedakan nama engine end-to-end lewat service
        # dengan menukar default engine pada instance TTSService kedua.
        config_other_default = TTSConfig(engine="second_fake_test_engine", cache_dir=str(tmp_path / "cache"))
        service_other_default = TTSService(config_other_default)

        result_a = await service.synthesize(text="Sama", voice="v1", speed=1.0, pitch=1.0, volume=1.0)
        result_b = await service_other_default.synthesize(text="Sama", voice="v1", speed=1.0, pitch=1.0, volume=1.0)

        assert result_a.audio_file_path != result_b.audio_file_path
    finally:
        del EngineFactory._registry["second_fake_test_engine"]


# --- Default voice fallback (safety-net) ------------------------------------


class FakeEngineWithVoices(TTSEngine):
    """Engine palsu dengan voice discovery (untuk verifikasi fallback default voice)."""

    def __init__(self, config: TTSConfig) -> None:
        self.call_count = 0
        self.last_voice: str | None = None

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        self.call_count += 1
        self.last_voice = voice
        return _make_tone_wav()

    async def list_voices(self):
        from announcement_server.tts.voice_profile import VoiceProfile

        return [
            VoiceProfile(id="v1", engine="fake_voices_engine", name="v1", source="x", available=True),
            VoiceProfile(id="v2", engine="fake_voices_engine", name="v2", source="x", available=True),
        ]


@pytest.fixture(autouse=True)
def register_fake_voices_engine():
    EngineFactory.register("fake_voices_engine", FakeEngineWithVoices)
    yield
    del EngineFactory._registry["fake_voices_engine"]


async def test_synthesize_default_voice_available_uses_it_as_is(tmp_path: Path) -> None:
    """Jika `tts.default_voice` benar-benar tersedia di engine, TIDAK ada fallback."""
    config = TTSConfig(
        engine="fake_voices_engine",
        default_voice="v1",
        cache_dir=str(tmp_path / "cache"),
    )
    service = TTSService(config)
    fake: FakeEngineWithVoices = service._engine_manager.get()  # type: ignore[assignment]

    result = await service.synthesize(text="Halo", voice="v1", speed=1.0, pitch=1.0, volume=1.0)

    assert result.cache_hit is False
    assert fake.last_voice == "v1"


async def test_synthesize_default_voice_missing_falls_back_to_first_available(tmp_path: Path) -> None:
    """Safety-net: default voice tidak tersedia -> fallback ke voice pertama yang ada,
    supaya request tanpa `voice` tetap berhasil (bukan langsung failed)."""
    config = TTSConfig(
        engine="fake_voices_engine",
        default_voice="en_US-tidak-ada",
        cache_dir=str(tmp_path / "cache"),
    )
    service = TTSService(config)
    fake: FakeEngineWithVoices = service._engine_manager.get()  # type: ignore[assignment]

    result = await service.synthesize(text="Halo", voice="en_US-tidak-ada", speed=1.0, pitch=1.0, volume=1.0)

    assert result.cache_hit is False
    assert fake.call_count == 1
    assert fake.last_voice == "v1"  # fallback ke voice pertama yang tersedia


async def test_synthesize_explicit_voice_missing_does_not_fall_back(tmp_path: Path) -> None:
    """Voice EKSPLIT yang tidak tersedia TIDAK boleh di-fallback (semantik terdokumentasi:
    request eksplisit dengan voice salah tetap memakai voice tsb — validasi/discovery tetap
    tanggung jawab engine)."""
    config = TTSConfig(
        engine="fake_voices_engine",
        default_voice="v1",
        cache_dir=str(tmp_path / "cache"),
    )
    service = TTSService(config)
    fake: FakeEngineWithVoices = service._engine_manager.get()  # type: ignore[assignment]

    result = await service.synthesize(text="Halo", voice="eksplisit-salah", speed=1.0, pitch=1.0, volume=1.0)

    assert result.cache_hit is False
    assert fake.last_voice == "eksplisit-salah"  # voice eksplisit dikirim apa adanya


# --- Phase 13 — Multi-Engine Validation: urutan Queue lintas 3 engine sekaligus --


async def test_queue_sequence_piper_espeak_styletts2_piper_does_not_conflict(tmp_path: Path) -> None:
    """VALIDASI QUEUE (Phase 13): membuktikan urutan Piper -> eSpeak -> StyleTTS2 -> Piper
    lewat SATU TTSService/TTSEngineManager (persis seperti QueueWorker memproses item
    berurutan dari QueueManager) tidak saling mengganggu -- tidak ada state yang bocor
    antar-engine, dan engine yang SAMA dipanggil dua kali (di awal & akhir urutan) tetap
    menghasilkan cache HIT yang benar meski ada 2 engine lain diproses di antaranya."""
    EngineFactory.register("fake_piper_seq", FakeEngine)
    EngineFactory.register("fake_espeak_seq", FakeEngine)
    EngineFactory.register("fake_styletts2_seq", FakeEngine)
    try:
        config = TTSConfig(
            engine="fake_piper_seq",
            additional_engines=["fake_espeak_seq", "fake_styletts2_seq"],
            cache_dir=str(tmp_path / "cache"),
        )
        service = TTSService(config)
        piper_engine_instance = service.engine_manager.get("fake_piper_seq")
        espeak_engine_instance = service.engine_manager.get("fake_espeak_seq")
        styletts2_engine_instance = service.engine_manager.get("fake_styletts2_seq")

        # Urutan PERSIS seperti yang diminta Phase 13: Piper -> eSpeak -> StyleTTS2 -> Piper.
        result_piper_1 = await service.synthesize(
            text="Pengumuman 1", voice="v1", speed=1.0, pitch=1.0, volume=1.0, engine="fake_piper_seq"
        )
        result_espeak = await service.synthesize(
            text="Pengumuman 1", voice="v1", speed=1.0, pitch=1.0, volume=1.0, engine="fake_espeak_seq"
        )
        result_styletts2 = await service.synthesize(
            text="Pengumuman 1", voice="v1", speed=1.0, pitch=1.0, volume=1.0, engine="fake_styletts2_seq"
        )
        result_piper_2 = await service.synthesize(
            text="Pengumuman 1", voice="v1", speed=1.0, pitch=1.0, volume=1.0, engine="fake_piper_seq"
        )

        # Tidak ada exception di atas (assert implisit -- kode ini tidak akan sampai sini jika ada).

        # Cache tetap engine-aware: teks/voice/parameter identik, tapi engine berbeda -> file cache berbeda.
        assert result_piper_1.audio_file_path != result_espeak.audio_file_path
        assert result_espeak.audio_file_path != result_styletts2.audio_file_path
        assert result_piper_1.audio_file_path != result_styletts2.audio_file_path

        # Panggilan Piper ke-2 (setelah 2 engine lain diproses di antaranya) HARUS cache HIT
        # terhadap panggilan Piper ke-1 -- membuktikan tidak ada state yang bocor/rusak akibat
        # engine lain yang diproses di tengah urutan.
        assert result_piper_2.audio_file_path == result_piper_1.audio_file_path
        assert result_piper_2.cache_hit is True

        # Setiap engine instance HANYA dipanggil sesuai jumlah cache MISS-nya sendiri --
        # tidak ada pemanggilan silang ke engine yang salah.
        assert piper_engine_instance.call_count == 1  # panggilan ke-2 adalah cache hit, engine tidak dipanggil lagi
        assert espeak_engine_instance.call_count == 1
        assert styletts2_engine_instance.call_count == 1
    finally:
        del EngineFactory._registry["fake_piper_seq"]
        del EngineFactory._registry["fake_espeak_seq"]
        del EngineFactory._registry["fake_styletts2_seq"]
