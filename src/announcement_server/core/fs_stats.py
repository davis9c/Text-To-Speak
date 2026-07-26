"""Utilitas statistik direktori (Phase 10 — Dashboard API).

Dipakai bersama oleh ``AudioCache`` (Phase 3, ``tts/cache.py``) dan
``AudioAssetResolver`` (Phase 7, ``announcement/asset_resolver.py``)
untuk melaporkan jumlah & ukuran file cache masing-masing lewat
``GET /status``/``GET /metrics`` — tanpa menduplikasi logika scan
direktori di kedua tempat. Diletakkan di ``core/`` (bukan ``tts/`` atau
``announcement/``) karena dipakai lintas domain, murni fungsi stdlib.
"""

from __future__ import annotations

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
