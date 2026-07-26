"""Unit test untuk compute_directory_stats (Phase 10 — Dashboard API)."""

from __future__ import annotations

from pathlib import Path

from announcement_server.core.fs_stats import compute_directory_stats


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
