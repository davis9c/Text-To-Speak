"""Unit test untuk cache cleanup (Phase 14 — Production Hardening)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from announcement_server.core.fs_stats import cleanup_directory
from announcement_server.tts.cache import AudioCache


def _touch_with_age(path: Path, age_days: float) -> None:
    path.write_bytes(b"x" * 10)
    old_time = time.time() - (age_days * 86400)
    os.utime(path, (old_time, old_time))


def test_cleanup_directory_none_max_age_deletes_nothing(tmp_path: Path) -> None:
    _touch_with_age(tmp_path / "old.wav", age_days=100)
    deleted, freed = cleanup_directory(tmp_path, max_age_days=None)
    assert (deleted, freed) == (0, 0)
    assert (tmp_path / "old.wav").exists()


def test_cleanup_directory_deletes_old_files_only(tmp_path: Path) -> None:
    _touch_with_age(tmp_path / "old.wav", age_days=10)
    _touch_with_age(tmp_path / "new.wav", age_days=1)

    deleted, freed = cleanup_directory(tmp_path, max_age_days=5)

    assert deleted == 1
    assert freed == 10
    assert not (tmp_path / "old.wav").exists()
    assert (tmp_path / "new.wav").exists()


def test_cleanup_directory_missing_directory_returns_zero(tmp_path: Path) -> None:
    deleted, freed = cleanup_directory(tmp_path / "tidak-ada", max_age_days=1)
    assert (deleted, freed) == (0, 0)


async def test_audio_cache_cleanup_deletes_old_files(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    _touch_with_age(tmp_path / "old.wav", age_days=10)
    _touch_with_age(tmp_path / "new.wav", age_days=1)

    deleted, freed = await cache.cleanup(max_age_days=5)

    assert deleted == 1
    assert freed == 10


async def test_audio_cache_cleanup_none_deletes_nothing(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    _touch_with_age(tmp_path / "old.wav", age_days=100)
    deleted, freed = await cache.cleanup(max_age_days=None)
    assert (deleted, freed) == (0, 0)
