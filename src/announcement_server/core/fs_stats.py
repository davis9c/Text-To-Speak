"""Utilitas statistik direktori (Phase 10 — Dashboard API).

Dipakai bersama oleh ``AudioCache`` (Phase 3, ``tts/cache.py``) dan
``AudioAssetResolver`` (Phase 7, ``announcement/asset_resolver.py``)
untuk melaporkan jumlah & ukuran file cache masing-masing lewat
``GET /status``/``GET /metrics`` — tanpa menduplikasi logika scan
direktori di kedua tempat. Diletakkan di ``core/`` (bukan ``tts/`` atau
``announcement/``) karena dipakai lintas domain, murni fungsi stdlib.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

# Default TTL cache statistik direktori. `GET /status` & `GET /metrics` dipanggil
# oleh dashboard secara polling (detik-an), sementara scan direktori cache
# adalah operasi O(jumlah_file) yang menyentuh filesystem. Tanpa TTL, satu
# polling = 2 scan penuh (cache TTS + cache announcement). Angka ini tidak
# perlu presisi real-time (bukan metrik operasional kritis), jadi TTL pendek
# sudah cukup untuk memangkas mayoritas pekerjaan berulang.
DEFAULT_STATS_TTL_SECONDS = 5.0


def compute_directory_stats(directory: Path) -> tuple[int, int]:
    """Mengembalikan ``(jumlah_file, total_ukuran_bytes)`` dari seluruh file (rekursif) di ``directory``.

    Mengembalikan ``(0, 0)`` jika direktori belum ada sama sekali (mis.
    belum pernah ada cache yang ditulis) — bukan dianggap error.

    Implementasi memakai ``os.scandir`` (bukan ``Path.rglob``) karena ``rglob``
    membangun objek ``Path`` untuk SETIAP entri (file maupun subdirektori) dan
    setiap pemanggil harus melakukan ``is_file()`` + ``stat()`` — jadi minimal
    dua syscall per file. ``os.scandir`` memberi ``DirEntry`` yang tipe-nya
    sudah diketahui dari entri direktori, sehingga ``is_file()`` tidak perlu
    syscall tambahan dan hanya ``stat()`` yang tersisa untuk ukuran. Pada
    direktori cache berisi ratusan/ribuan file, ini memangkas setengah syscall
    sekaligus seluruh alokasi objek ``Path``.
    """
    try:
        if not directory.is_dir():
            return 0, 0
    except OSError:
        return 0, 0

    file_count = 0
    total_size = 0
    stack = [str(directory)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        total_size += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        # File hilang/terkunci saat scan (mis. cleanup yang
                        # berjalan bersamaan) — dilewati, bukan menggagalkan
                        # seluruh scan.
                        continue
                    file_count += 1
        except OSError:
            continue
    return file_count, total_size


class DirectoryStatsCache:
    """Memo TTL untuk ``compute_directory_stats`` pada satu direktori.

    Dipakai oleh ``AudioCache`` (Phase 3) dan ``AudioAssetResolver`` (Phase 7)
    supaya polling dashboard (``GET /status``/``/metrics``) tidak memindai
    ulang seluruh direktori cache pada setiap request. ``invalidate()``
    dipanggil setiap kali isi direktori berubah karena aplikasi sendiri
    (``cleanup``), supaya angka tetap akurat segera setelah perubahan itu.
    """

    def __init__(self, directory: Path, *, ttl_seconds: float = DEFAULT_STATS_TTL_SECONDS) -> None:
        """Menyimpan direktori yang dipantau, TTL, dan hasil scan terakhir (None = belum pernah di-scan)."""
        self._directory = directory
        self._ttl_seconds = ttl_seconds
        self._cached: tuple[int, int] | None = None
        self._cached_at = 0.0

    def invalidate(self) -> None:
        """Membuang hasil scan tersimpan supaya request berikutnya memindai ulang."""
        self._cached = None

    async def get_stats(self) -> tuple[int, int]:
        """Mengembalikan ``(jumlah_file, total_ukuran_bytes)``, memakai hasil scan terakhir bila masih dalam TTL."""
        now = time.monotonic()
        if self._cached is not None and (now - self._cached_at) < self._ttl_seconds:
            return self._cached

        stats = await asyncio.to_thread(compute_directory_stats, self._directory)
        # Scan di thread worker bisa baru selesai SETELAH `now` di atas
        # dihitung, jadi waktu pengisian cache diambil ulang setelah scan —
        # supaya TTL diukur dari saat data benar-benar tersedia, bukan dari
        # saat scan dimulai.
        self._cached = stats
        self._cached_at = time.monotonic()
        return stats


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
