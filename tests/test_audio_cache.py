"""Unit test untuk AudioCache (SHA256 keying, atomic write, hit/miss)."""

from __future__ import annotations

from pathlib import Path

import pytest

from announcement_server.tts.cache import AudioCache


@pytest.fixture()
def cache(tmp_path: Path) -> AudioCache:
    return AudioCache(tmp_path / "audio_cache")


def test_cache_dir_created_automatically(tmp_path: Path) -> None:
    cache_dir = tmp_path / "nested" / "audio_cache"
    AudioCache(cache_dir)
    assert cache_dir.is_dir()


def test_compute_key_is_deterministic() -> None:
    key1 = AudioCache.compute_key(engine="piper", voice="v1", text="halo", speed=1.0, pitch=1.0, volume=1.0)
    key2 = AudioCache.compute_key(engine="piper", voice="v1", text="halo", speed=1.0, pitch=1.0, volume=1.0)
    assert key1 == key2
    assert len(key1) == 64  # SHA256 hexdigest


@pytest.mark.parametrize(
    "field,changed_kwargs",
    [
        ("text", {"text": "beda"}),
        ("voice", {"voice": "voice_lain"}),
        ("speed", {"speed": 1.5}),
        ("pitch", {"pitch": 1.2}),
        ("volume", {"volume": 0.5}),
    ],
)
def test_compute_key_changes_when_any_param_changes(field: str, changed_kwargs: dict) -> None:
    base_kwargs = {"engine": "piper", "voice": "v1", "text": "halo", "speed": 1.0, "pitch": 1.0, "volume": 1.0}
    base_key = AudioCache.compute_key(**base_kwargs)
    modified_key = AudioCache.compute_key(**{**base_kwargs, **changed_kwargs})
    assert base_key != modified_key, f"key harus berubah ketika {field} berubah"


async def test_get_returns_none_when_cache_miss(cache: AudioCache) -> None:
    result = await cache.get("nonexistent_key")
    assert result is None


async def test_put_then_get_roundtrip(cache: AudioCache) -> None:
    key = "some_cache_key"
    stored_path = await cache.put(key, b"FAKE_AUDIO_BYTES")

    assert stored_path.is_file()
    assert stored_path.read_bytes() == b"FAKE_AUDIO_BYTES"

    hit_path = await cache.get(key)
    assert hit_path == stored_path


async def test_put_does_not_leave_tmp_file(cache: AudioCache, tmp_path: Path) -> None:
    await cache.put("some_key", b"data")
    tmp_files = list((tmp_path / "audio_cache").glob("*.tmp"))
    assert tmp_files == []


async def test_put_overwrites_existing_key(cache: AudioCache) -> None:
    await cache.put("key", b"pertama")
    stored_path = await cache.put("key", b"kedua")
    assert stored_path.read_bytes() == b"kedua"
