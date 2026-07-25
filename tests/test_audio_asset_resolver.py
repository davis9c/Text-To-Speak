"""Unit test untuk AudioAssetResolver (Phase 7).

Sama seperti ``test_piper_engine.py`` (Phase 3), binary ``ffmpeg`` asli
tidak tersedia di lingkungan CI/sandbox — test di sini memakai *fake
ffmpeg executable* (script Python kecil yang meniru perilaku CLI ffmpeg:
menulis file WAV ke argumen output terakhir, exit code sesuai skenario).
Ini memvalidasi seluruh "plumbing" subprocess tanpa bergantung pada
instalasi ffmpeg sungguhan.
"""

from __future__ import annotations

import stat
import sys
import wave
from pathlib import Path

import pytest

from announcement_server.core.config import AnnouncementConfig
from announcement_server.core.exceptions import (
    AudioAssetNotFoundError,
    AudioConversionError,
    AudioConversionUnavailableError,
)
from announcement_server.announcement.asset_resolver import AudioAssetResolver

FAKE_FFMPEG_SCRIPT = '''#!{python_executable}
import sys
import wave

args = sys.argv[1:]
output_file = args[-1]

if "FAIL_EXIT_CODE" in " ".join(args):
    sys.stderr.write("simulasi kegagalan ffmpeg\\n")
    sys.exit(1)

if "FAIL_TIMEOUT" in " ".join(args):
    import time
    time.sleep(5)
    sys.exit(0)

with wave.open(output_file, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(b"\\x00\\x00" * 100)
sys.exit(0)
'''


@pytest.fixture()
def sounds_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "sounds"
    directory.mkdir()
    return directory


@pytest.fixture()
def fake_ffmpeg_binary(tmp_path: Path) -> Path:
    script_path = tmp_path / "fake_ffmpeg.py"
    script_path.write_text(FAKE_FFMPEG_SCRIPT.format(python_executable=sys.executable))
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script_path


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(22050)
        writer.writeframes(b"\x00\x00" * 50)


@pytest.fixture()
def config(tmp_path: Path, sounds_dir: Path, fake_ffmpeg_binary: Path) -> AnnouncementConfig:
    return AnnouncementConfig(
        sounds_dir=str(sounds_dir),
        ffmpeg_binary_path=str(fake_ffmpeg_binary),
        converted_cache_dir=str(tmp_path / "cache" / "announcement_audio"),
        conversion_timeout_seconds=2.0,
    )


async def test_resolve_wav_file_returns_directly_without_conversion(sounds_dir: Path, config: AnnouncementConfig) -> None:
    wav_path = sounds_dir / "bell.wav"
    _write_wav(wav_path)

    resolver = AudioAssetResolver(config)
    resolved_path, cache_hit = await resolver.resolve("bell.wav")

    assert resolved_path == str(wav_path)
    assert cache_hit is True


async def test_resolve_nested_wav_file(sounds_dir: Path, config: AnnouncementConfig) -> None:
    nested_dir = sounds_dir / "alarms"
    nested_dir.mkdir()
    wav_path = nested_dir / "fire.wav"
    _write_wav(wav_path)

    resolver = AudioAssetResolver(config)
    resolved_path, cache_hit = await resolver.resolve("alarms/fire.wav")

    assert resolved_path == str(wav_path)
    assert cache_hit is True


async def test_resolve_missing_file_raises_not_found(config: AnnouncementConfig) -> None:
    resolver = AudioAssetResolver(config)
    with pytest.raises(AudioAssetNotFoundError):
        await resolver.resolve("tidak-ada.wav")


async def test_resolve_path_traversal_raises_not_found(sounds_dir: Path, config: AnnouncementConfig) -> None:
    resolver = AudioAssetResolver(config)
    with pytest.raises(AudioAssetNotFoundError):
        await resolver.resolve("../../../etc/passwd")


async def test_resolve_mp3_converts_via_ffmpeg_and_caches(sounds_dir: Path, config: AnnouncementConfig) -> None:
    mp3_path = sounds_dir / "jingle.mp3"
    mp3_path.write_bytes(b"dummy-mp3-bytes")

    resolver = AudioAssetResolver(config)
    resolved_path, cache_hit = await resolver.resolve("jingle.mp3")

    assert cache_hit is False  # baru dikonversi
    assert Path(resolved_path).exists()
    assert Path(resolved_path).suffix == ".wav"
    assert Path(resolved_path).parent == Path(config.converted_cache_dir)

    # Panggilan kedua untuk file sumber yang SAMA persis harus memakai cache.
    resolved_path_2, cache_hit_2 = await resolver.resolve("jingle.mp3")
    assert resolved_path_2 == resolved_path
    assert cache_hit_2 is True


async def test_resolve_mp3_without_ffmpeg_raises_unavailable(sounds_dir: Path, tmp_path: Path) -> None:
    mp3_path = sounds_dir / "jingle.mp3"
    mp3_path.write_bytes(b"dummy-mp3-bytes")

    config = AnnouncementConfig(
        sounds_dir=str(sounds_dir),
        ffmpeg_binary_path="ffmpeg_binary_yang_tidak_ada_xyz",
        converted_cache_dir=str(tmp_path / "cache"),
    )
    resolver = AudioAssetResolver(config)
    with pytest.raises(AudioConversionUnavailableError):
        await resolver.resolve("jingle.mp3")


async def test_resolve_mp3_ffmpeg_failure_raises_conversion_error(sounds_dir: Path, config: AnnouncementConfig) -> None:
    mp3_path = sounds_dir / "FAIL_EXIT_CODE.mp3"
    mp3_path.write_bytes(b"dummy-mp3-bytes")

    resolver = AudioAssetResolver(config)
    with pytest.raises(AudioConversionError):
        await resolver.resolve("FAIL_EXIT_CODE.mp3")


async def test_resolve_mp3_ffmpeg_timeout_raises_conversion_error(sounds_dir: Path, config: AnnouncementConfig) -> None:
    mp3_path = sounds_dir / "FAIL_TIMEOUT.mp3"
    mp3_path.write_bytes(b"dummy-mp3-bytes")

    resolver = AudioAssetResolver(config)
    with pytest.raises(AudioConversionError):
        await resolver.resolve("FAIL_TIMEOUT.mp3")
