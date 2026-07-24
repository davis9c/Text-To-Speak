"""Audio Cache — cache hasil sintesis TTS berbasis SHA256.

Cache disimpan sebagai file WAV langsung di disk (bukan di memory) karena
file audio bisa berukuran besar dan harus tetap ada meski proses server
di-restart (Windows Service pada Phase 12 akan sering restart otomatis).
Key cache dihitung dari SHA256 atas seluruh parameter yang memengaruhi
hasil audio (engine, voice, text, speed, pitch, volume) — jika salah satu
berubah, key berubah, cache otomatis miss (tidak butuh invalidasi manual).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioCache:
    """Cache file audio berbasis SHA256 di filesystem."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_key(*, engine: str, voice: str, text: str, speed: float, pitch: float, volume: float) -> str:
        """Menghitung SHA256 dari seluruh parameter yang memengaruhi hasil audio.

        Format payload menyertakan nama field secara eksplisit (bukan
        sekadar digabung dengan pemisah) untuk menghindari tabrakan key
        yang secara teori bisa terjadi jika nilai field mengandung
        karakter pemisah itu sendiri.
        """
        payload = (
            f"engine={engine}\n"
            f"voice={voice}\n"
            f"speed={speed:.3f}\n"
            f"pitch={pitch:.3f}\n"
            f"volume={volume:.3f}\n"
            f"text={text}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def path_for(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.wav"

    async def get(self, cache_key: str) -> Path | None:
        """Mengembalikan path file cache jika ada, atau ``None`` jika cache miss."""
        path = self.path_for(cache_key)
        exists = await asyncio.to_thread(path.is_file)
        return path if exists else None

    async def put(self, cache_key: str, audio_bytes: bytes) -> Path:
        """Menyimpan audio ke cache. Mengembalikan path file yang tersimpan.

        Ditulis ke file sementara lalu di-rename (atomic pada sistem file
        yang umum, termasuk NTFS) untuk mencegah proses lain membaca file
        cache yang belum selesai ditulis (partial read) pada sistem yang
        berjalan concurrent.
        """
        final_path = self.path_for(cache_key)
        tmp_path = final_path.with_suffix(".tmp")

        def _write() -> None:
            tmp_path.write_bytes(audio_bytes)
            tmp_path.replace(final_path)

        await asyncio.to_thread(_write)
        logger.debug("Audio disimpan ke cache: key=%s path=%s", cache_key[:12], final_path)
        return final_path
