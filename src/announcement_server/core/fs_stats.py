"""Utilitas statistik direktori (Phase 10 — Dashboard API).

Dipakai bersama oleh ``AudioCache`` (Phase 3, ``tts/cache.py``) dan
``AudioAssetResolver`` (Phase 7, ``announcement/asset_resolver.py``)
untuk melaporkan jumlah & ukuran file cache masing-masing lewat
``GET /status``/``GET /metrics`` — tanpa menduplikasi logika scan
direktori di kedua tempat. Diletakkan di ``core/`` (bukan ``tts/`` atau
``announcement/``) karena dipakai lintas domain, murni fungsi stdlib.
"""

from __future__ import annotations

import time
from pathlib import Path


def compute_directory_stats(directory: Path) -> tuple[int, int]:
    """Mengembalikan ``(jumlah_file, total_ukuran_bytes)`` dari seluruh file (rekursif) di ``directory``.

    Mengembalikan ``(0, 0)`` jika direktori belum ada sama sekali (mis.
    belum pernah ada cache yang ditulis) — bukan dianggap error.
    """
    if not directory.is_dir():
        return 0, 0
    file_count = 0
    total_size = 0
    for path in directory.rglob("*"):
        if path.is_file():
            file_count += 1
            total_size += path.stat().st_size
    return file_count, total_size


def cleanup_directory(directory: Path, *, max_age_days: float | None) -> tuple[int, int]:
    """Menghapus file (rekursif) di ``directory`` yang lebih tua dari ``max_age_days`` (Phase 14).

    Mengembalikan ``(jumlah_file_dihapus, total_bytes_dibebaskan)``.
    ``max_age_days=None`` berarti tidak menghapus apa pun (mengembalikan
    ``(0, 0)``) — cache cleanup bersifat opt-in lewat konfigurasi.
    File yang gagal dihapus (mis. sedang dipakai) dilewati secara graceful.
    """
    if max_age_days is None or not directory.is_dir():
        return 0, 0
    cutoff = time.time() - (max_age_days * 86400)
    deleted_count = 0
    freed_bytes = 0
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            if stat.st_mtime < cutoff:
                size = stat.st_size
                path.unlink()
                deleted_count += 1
                freed_bytes += size
        except OSError:
            continue
    return deleted_count, freed_bytes
