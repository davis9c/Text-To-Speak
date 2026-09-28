"""Unit test untuk compute_directory_stats (Phase 10 — Dashboard API)."""

from __future__ import annotations

from pathlib import Path

from announcement_server.core.fs_stats import DirectoryStatsCache, compute_directory_stats


def test_nonexistent_directory_returns_zero(tmp_path: Path) -> None:
    missing = tmp_path / "belum-ada"
    file_count, total_size = compute_directory_stats(missing)
    assert (file_count, total_size) == (0, 0)


def test_empty_directory_returns_zero(tmp_path: Path) -> None:
    file_count, total_size = compute_directory_stats(tmp_path)
    assert (file_count, total_size) == (0, 0)


def test_counts_files_and_sums_size(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"x" * 100)
    (tmp_path / "b.wav").write_bytes(b"y" * 250)

    file_count, total_size = compute_directory_stats(tmp_path)

    assert file_count == 2
    assert total_size == 350


def test_counts_files_recursively_in_subdirectories(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"x" * 10)
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "b.wav").write_bytes(b"y" * 20)

    file_count, total_size = compute_directory_stats(tmp_path)

    assert file_count == 2
    assert total_size == 30


def test_ignores_subdirectories_themselves_as_entries(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    file_count, total_size = compute_directory_stats(tmp_path)
    assert (file_count, total_size) == (0, 0)


def test_counts_deeply_nested_and_empty_subdirectories(tmp_path: Path) -> None:
    """Scan berbasis ``os.scandir`` harus tetap rekursif dan tidak menghitung
    subdirektori kosong sebagai file."""
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (tmp_path / "a" / "top.wav").write_bytes(b"x" * 5)
    (deep / "deep.wav").write_bytes(b"y" * 7)
    (tmp_path / "a" / "b" / "empty").mkdir()

    assert compute_directory_stats(tmp_path) == (2, 12)


# --- DirectoryStatsCache (memo TTL untuk polling dashboard) -------------------


async def test_stats_cache_returns_same_values_as_direct_scan(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"x" * 10)
    cache = DirectoryStatsCache(tmp_path)

    assert await cache.get_stats() == (1, 10)
    assert await cache.get_stats() == (1, 10)


async def test_stats_cache_serves_repeat_reads_within_ttl(tmp_path: Path) -> None:
    """Perubahan di dalam TTL TIDAK terlihat — itulah tujuan memo ini: polling
    dashboard (``GET /status``/``/metrics``) tidak boleh memindai ulang direktori
    cache pada setiap request."""
    (tmp_path / "a.wav").write_bytes(b"x" * 10)
    cache = DirectoryStatsCache(tmp_path, ttl_seconds=3600.0)

    assert await cache.get_stats() == (1, 10)

    (tmp_path / "b.wav").write_bytes(b"y" * 99)
    assert await cache.get_stats() == (1, 10)  # masih hasil tersimpan


async def test_stats_cache_invalidate_forces_rescan(tmp_path: Path) -> None:
    """`invalidate()` (dipanggil setelah cache cleanup) membuat angka langsung
    akurat tanpa menunggu TTL habis."""
    (tmp_path / "a.wav").write_bytes(b"x" * 10)
    cache = DirectoryStatsCache(tmp_path, ttl_seconds=3600.0)

    assert await cache.get_stats() == (1, 10)

    (tmp_path / "b.wav").write_bytes(b"y" * 99)
    cache.invalidate()
    assert await cache.get_stats() == (2, 109)


async def test_stats_cache_expires_after_ttl(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"x" * 10)
    cache = DirectoryStatsCache(tmp_path, ttl_seconds=0.0)

    assert await cache.get_stats() == (1, 10)

    (tmp_path / "b.wav").write_bytes(b"y" * 99)
    assert await cache.get_stats() == (2, 109)  # TTL 0 -> selalu scan ulang


async def test_stats_cache_handles_missing_directory(tmp_path: Path) -> None:
    cache = DirectoryStatsCache(tmp_path / "belum-ada")
    assert await cache.get_stats() == (0, 0)
