"""Unit test untuk AudioProcessor (post-processing volume & pitch)."""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from announcement_server.tts.audio_processor import AudioProcessor


def _make_sine_wav(freq: float = 440.0, duration: float = 0.2, rate: int = 22050, amplitude: int = 8000) -> bytes:
    """Membuat WAV sintetis (mono, 16-bit) berisi gelombang sinus untuk keperluan test."""
    n_samples = int(duration * rate)
    frames = bytearray()
    for i in range(n_samples):
        value = int(amplitude * math.sin(2 * math.pi * freq * i / rate))
        frames += struct.pack("<h", value)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(bytes(frames))
    return buffer.getvalue()


def _read_wav_params(wav_bytes: bytes) -> wave._wave_params:
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        return reader.getparams()


@pytest.fixture()
def processor() -> AudioProcessor:
    return AudioProcessor()


@pytest.fixture()
def sample_wav() -> bytes:
    return _make_sine_wav()


def test_apply_volume_noop_at_1_0(processor: AudioProcessor, sample_wav: bytes) -> None:
    assert processor.apply_volume(sample_wav, 1.0) == sample_wav


def test_apply_volume_changes_amplitude_not_duration(processor: AudioProcessor, sample_wav: bytes) -> None:
    louder = processor.apply_volume(sample_wav, 1.5)
    original_params = _read_wav_params(sample_wav)
    louder_params = _read_wav_params(louder)

    assert louder != sample_wav
    assert louder_params.nframes == original_params.nframes
    assert louder_params.framerate == original_params.framerate


def test_apply_volume_mute(processor: AudioProcessor, sample_wav: bytes) -> None:
    muted = processor.apply_volume(sample_wav, 0.0)
    with wave.open(io.BytesIO(muted), "rb") as reader:
        frames = reader.readframes(reader.getnframes())
    assert frames == b"\x00" * len(frames)


def test_apply_pitch_noop_at_1_0(processor: AudioProcessor, sample_wav: bytes) -> None:
    assert processor.apply_pitch(sample_wav, 1.0) == sample_wav


def test_apply_pitch_up_reduces_frame_count(processor: AudioProcessor, sample_wav: bytes) -> None:
    """Pitch naik -> jumlah sample berkurang (efek samping: durasi lebih pendek), frame rate header tetap sama."""
    original_params = _read_wav_params(sample_wav)
    higher = processor.apply_pitch(sample_wav, 1.5)
    higher_params = _read_wav_params(higher)

    assert higher_params.framerate == original_params.framerate
    assert higher_params.nframes < original_params.nframes


def test_apply_pitch_down_increases_frame_count(processor: AudioProcessor, sample_wav: bytes) -> None:
    original_params = _read_wav_params(sample_wav)
    lower = processor.apply_pitch(sample_wav, 0.7)
    lower_params = _read_wav_params(lower)

    assert lower_params.framerate == original_params.framerate
    assert lower_params.nframes > original_params.nframes


def test_processed_wav_remains_valid_wave_file(processor: AudioProcessor, sample_wav: bytes) -> None:
    """Output apply_volume/apply_pitch harus tetap file WAV valid yang bisa dibuka ulang."""
    processed = processor.apply_pitch(processor.apply_volume(sample_wav, 1.3), 1.2)
    with wave.open(io.BytesIO(processed), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        assert reader.getnframes() > 0
