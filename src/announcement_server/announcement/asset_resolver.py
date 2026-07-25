"""Audio Asset Resolver (Phase 7 — Announcement Engine).

Menyiapkan file audio SIAP PUTAR untuk item bertipe ``audio`` (bell,
alarm, jingle, atau file WAV/MP3 apa pun) — analog dengan apa yang
dilakukan ``TTSService`` (Phase 3) untuk item bertipe ``tts``, tapi tanpa
sintesis suara: file yang diminta murni divalidasi, dan dikonversi ke WAV
lewat ``ffmpeg`` bila perlu (mis. sumber ``.mp3``), supaya
``PlaybackManager`` (Phase 4, hanya memahami WAV lewat modul stdlib
``wave``) bisa memutarnya tanpa perubahan apa pun.

Desain penting — ``ffmpeg`` bersifat OPSIONAL (graceful degradation, pola
identik dengan Piper pada Phase 3): file yang SUDAH berformat ``.wav``
diputar langsung tanpa pernah menyentuh ``ffmpeg`` sama sekali. ``ffmpeg``
hanya dipanggil untuk format lain, dan kegagalan mendeteksinya (binary
tidak ada) dilaporkan lewat ``AudioConversionUnavailableError`` — bukan
meng-crash server saat startup.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from pathlib import Path

from announcement_server.core.config import AnnouncementConfig
from announcement_server.core.exceptions import (
    AudioAssetNotFoundError,
    AudioConversionError,
    AudioConversionUnavailableError,
)

logger = logging.getLogger(__name__)

_WAV_EXTENSIONS = frozenset({".wav", ".wave"})


class AudioAssetResolver:
    """Resolve referensi file audio statis (mis. "sounds/bell.mp3") menjadi path WAV siap putar."""

    def __init__(self, config: AnnouncementConfig) -> None:
        self._sounds_dir = Path(config.sounds_dir)
        self._converted_cache_dir = Path(config.converted_cache_dir)
        self._ffmpeg_binary_path = config.ffmpeg_binary_path
        self._timeout_seconds = config.conversion_timeout_seconds

    async def resolve(self, relative_file: str) -> tuple[str, bool]:
        """Mengembalikan ``(path_wav_absolut, cache_hit)`` siap dipakai ``PlaybackManager.play()``.

        - File yang sudah ``.wav`` dikembalikan langsung (``cache_hit=True``,
          tidak ada konversi/penyalinan sama sekali).
        - File format lain (mis. ``.mp3``) dikonversi ke WAV lewat
          ``ffmpeg`` dan hasilnya di-cache di ``announcement.converted_cache_dir``
          (key = SHA256 dari path+mtime+size sumber) — pemanggilan berikutnya
          untuk file sumber yang sama persis langsung memakai cache
          (``cache_hit=True``) tanpa memanggil ``ffmpeg`` ulang.

        Melempar:
        - ``AudioAssetNotFoundError`` — file sumber tidak ditemukan, atau
          ``relative_file`` mencoba keluar dari ``sounds_dir`` (path traversal).
        - ``AudioConversionUnavailableError`` — file bukan ``.wav`` dan
          ``ffmpeg`` tidak terdeteksi.
        - ``AudioConversionError`` — ``ffmpeg`` gagal/timeout mengonversi.
        """
        source_path = self._resolve_source_path(relative_file)
        if not source_path.is_file():
            raise AudioAssetNotFoundError(
                f"File audio tidak ditemukan: {relative_file}",
                details={"file": relative_file},
            )

        if source_path.suffix.lower() in _WAV_EXTENSIONS:
            return str(source_path), True

        cached_path = self._cached_path_for(source_path)
        if cached_path.is_file():
            logger.debug("Audio asset cache hit: %s -> %s", relative_file, cached_path)
            return str(cached_path), True

        await self._convert_to_wav(source_path, cached_path)
        return str(cached_path), False

    def _resolve_source_path(self, relative_file: str) -> Path:
        """Menggabungkan ``relative_file`` ke ``sounds_dir``, MENOLAK path yang keluar dari direktori tsb.

        Mencegah path traversal (mis. ``"../../../Windows/System32/..."``)
        lewat request ``file`` yang datang dari client — prinsip yang sama
        seperti validasi path pada sistem apa pun yang menerima input path
        dari luar.
        """
        sounds_dir_resolved = self._sounds_dir.resolve()
        candidate = (self._sounds_dir / relative_file).resolve()
        if candidate != sounds_dir_resolved and sounds_dir_resolved not in candidate.parents:
            raise AudioAssetNotFoundError(
                f"Path file audio tidak valid (di luar direktori sounds): {relative_file}",
                details={"file": relative_file},
            )
        return candidate

    def _cached_path_for(self, source_path: Path) -> Path:
        stat = source_path.stat()
        signature = f"{source_path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        return self._converted_cache_dir / f"{digest}.wav"

    async def _convert_to_wav(self, source_path: Path, target_path: Path) -> None:
        """Memanggil ``ffmpeg`` sebagai subprocess ASINKRON untuk konversi ke WAV.

        Pola subprocess di sini SENGAJA dibuat identik dengan
        ``tts/piper_engine.py`` (Phase 3): ``asyncio.create_subprocess_exec``
        (bukan blocking ``subprocess.run``, supaya tidak membekukan seluruh
        server), ``asyncio.wait_for`` dengan timeout, dan penanganan
        ``FileNotFoundError``/exit code/timeout yang setara.
        """
        ffmpeg_path = shutil.which(self._ffmpeg_binary_path)
        if ffmpeg_path is None and Path(self._ffmpeg_binary_path).is_file():
            ffmpeg_path = self._ffmpeg_binary_path
        if ffmpeg_path is None:
            raise AudioConversionUnavailableError(
                f"ffmpeg tidak ditemukan (announcement.ffmpeg_binary_path='{self._ffmpeg_binary_path}') "
                f"— tidak dapat mengonversi '{source_path.name}' ke WAV. Lihat bagian 'Setup ffmpeg' "
                "pada README, atau simpan file dalam format .wav untuk melewati langkah konversi ini.",
                details={"ffmpeg_binary_path": self._ffmpeg_binary_path, "source_file": source_path.name},
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target_path.with_suffix(target_path.suffix + ".tmp")

        command = [
            ffmpeg_path,
            "-y",
            "-i",
            str(source_path),
            "-ar",
            "22050",
            "-ac",
            "1",
            str(tmp_target),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AudioConversionUnavailableError(
                f"ffmpeg tidak ditemukan di '{ffmpeg_path}'. Pastikan announcement.ffmpeg_binary_path "
                "pada config.yaml sudah benar dan ffmpeg sudah terinstall.",
            ) from exc
        except OSError as exc:
            raise AudioConversionUnavailableError(f"Gagal menjalankan ffmpeg: {exc}") from exc

        try:
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout_seconds)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            tmp_target.unlink(missing_ok=True)
            raise AudioConversionError(
                f"ffmpeg timeout setelah {self._timeout_seconds} detik mengonversi '{source_path.name}'.",
                details={"source_file": source_path.name, "timeout_seconds": self._timeout_seconds},
            ) from exc

        if process.returncode != 0 or not tmp_target.is_file():
            tmp_target.unlink(missing_ok=True)
            raise AudioConversionError(
                f"ffmpeg gagal mengonversi '{source_path.name}' ke WAV (exit code {process.returncode}).",
                details={"stderr": stderr.decode("utf-8", errors="replace")[:500]},
            )

        tmp_target.replace(target_path)
        logger.info("File audio dikonversi ke WAV: %s -> %s", source_path, target_path)
