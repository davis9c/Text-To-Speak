"""Unit test untuk TTSService, memakai FakeEngine agar tidak bergantung pada Piper asli."""

from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

import pytest

from announcement_server.core.config import TTSConfig
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

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        self.call_count += 1
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
    fake_engine: FakeEngine = service._engine  # type: ignore[assignment]

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
    fake_engine: FakeEngine = service._engine  # type: ignore[assignment]

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
