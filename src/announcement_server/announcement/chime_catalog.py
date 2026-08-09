"""Chime Catalog — daftar file audio chime yang tersedia.

Fitur: efek chime (mis. ``sounds/chime.wav``) adalah file audio statis yang
diputar SEKALI sebelum pengumuman utama (lihat ``queueing/pipeline_processor.py``).
Katalog ini menscan ``announcement.chime_dir`` (folder KHUSUS chime, secara
default ``sounds/chime/``) dan mengekspos daftar chime yang tersedia lewat
REST API (``GET /chimes``) supaya client (mis. dashboard web) bisa
menampilkan dropdown pemilihan chime.

Desain penting:
- Chime adalah SUPERSET natural dari file audio statis biasa — daftar chime
  di sini murni untuk DISCOVERY (menampilkan pilihan ke user); resolusi &
  pemutaran chime yang sebenarnya TETAP ditangani ``AudioAssetResolver``
  (Phase 7) persis seperti file audio lain. Karena itu ``ChimeProfile.file``
  selalu berupa path relatif terhadap ``sounds_dir`` — format yang SAMA
  dengan field ``chime`` pada request ``POST /speak``/``/zones/{name}/speak``
  dan ``ScheduleAnnouncementDefinition``.
- Folder chime tidak ada / kosong → daftar kosong (``[]``), bukan error
  (graceful degradation, pola yang sama dengan VoiceRegistry).
- Chime default ditandai lewat nama file: ``chime.wav`` (prioritas utama) atau
  ``default.<ext>``. Tujuannya supaya dropdown bisa menyorot pilihan bawaan.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from announcement_server.core.config import AnnouncementConfig

logger = logging.getLogger(__name__)

# Ekstensi audio yang dianggap chime (format non-WAV akan dikonversi ke WAV
# oleh AudioAssetResolver lewat ffmpeg saat diputar — lihat asset_resolver.py).
_AUDIO_EXTENSIONS = frozenset({".wav", ".wave", ".mp3", ".flac", ".ogg", ".aac", ".m4a"})

# Nama file (tanpa ekstensi) yang menandai chime default, urut prioritas.
_DEFAULT_CHIME_STEMS = ("chime", "default")


@dataclass(frozen=True)
class ChimeProfile:
    """Satu chime yang ditemukan di ``chime_dir`` (objek domain, mirip VoiceProfile)."""

    id: str
    """Identifier chime, unik dalam lingkup satu direktori (nama file tanpa ekstensi)."""

    name: str
    """Nama tampilan chime."""

    file: str
    """Path relatif terhadap ``sounds_dir`` (format sama dengan field ``chime`` pada request)."""

    is_default: bool
    """True jika chime ini adalah chime default (file bernama ``chime.*``/``default.*``)."""


class ChimeCatalog:
    """Menscan ``announcement.chime_dir`` dan menyediakan daftar chime yang tersedia.

    Scan dilakukan SETIAP kali ``list()`` dipanggil (bukan di-cache saat
    startup seperti VoiceRegistry) supaya file chime yang ditambahkan user
    tanpa restart server langsung muncul di dropdown.
    """

    def __init__(self, config: AnnouncementConfig) -> None:
        self._chime_dir = Path(config.chime_dir)
        self._sounds_dir = Path(config.sounds_dir)

    async def list(self) -> list[ChimeProfile]:
        """Mengembalikan seluruh chime di ``chime_dir``, diurutkan berdasarkan nama file.

        Folder chime tidak ada atau kosong → ``[]`` (bukan error).
        """
        return await asyncio.to_thread(self._list_sync)

    async def get_default(self) -> ChimeProfile | None:
        """Mengembalikan chime default (``chime.*``/``default.*``), atau None jika tidak ada."""
        return next((chime for chime in await self.list() if chime.is_default), None)

    def _list_sync(self) -> list[ChimeProfile]:
        if not self._chime_dir.is_dir():
            logger.debug("Direktori chime '%s' belum ada; daftar chime kosong.", self._chime_dir)
            return []

        profiles: list[ChimeProfile] = []
        try:
            entries = sorted(self._chime_dir.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            logger.warning("Gagal membaca direktori chime '%s': %s", self._chime_dir, exc)
            return []

        for entry in entries:
            if not entry.is_file() or entry.suffix.lower() not in _AUDIO_EXTENSIONS:
                continue
            try:
                relative = entry.relative_to(self._sounds_dir)
            except ValueError:
                # chime_dir di luar sounds_dir (konfigurasi user): tetap layani,
                # tapi path-nya memakai nama file saja agar tetap relatif & aman.
                relative = Path(entry.name)
            profiles.append(
                ChimeProfile(
                    id=entry.stem,
                    name=entry.stem,
                    file=relative.as_posix(),
                    is_default=entry.stem.lower() in _DEFAULT_CHIME_STEMS,
                )
            )
        return profiles
