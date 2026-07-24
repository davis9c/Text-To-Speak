"""Piper Engine.

Implementasi ``TTSEngine`` yang memanggil executable Piper
(https://github.com/rhasspy/piper) sebagai subprocess. Piper dipilih
sebagai engine default karena berjalan sepenuhnya offline (sesuai
kebutuhan "Offline TTS" pada roadmap) dan ringan untuk dijalankan di
Windows sebagai bagian dari Windows Service (Phase 12).

PENTING: Piper (binary + model suara) TIDAK disertakan dalam repository
ini — harus diunduh terpisah oleh operator dan path-nya dikonfigurasi
lewat ``tts.piper_binary_path`` / ``tts.piper_models_dir`` pada
``config/config.yaml``. Lihat README untuk instruksi instalasi.

Desain penting — subprocess asinkron, bukan blocking:
Pemanggilan Piper dilakukan lewat ``asyncio.create_subprocess_exec`` (bukan
``subprocess.run``) karena kode ini berjalan di dalam event loop yang sama
dengan seluruh HTTP request lain (FastAPI + QueueWorker berbagi satu event
loop). Memanggil subprocess secara blocking akan membekukan SELURUH server
(termasuk endpoint /health) selama proses TTS berjalan — tidak dapat
diterima untuk sistem yang berjalan 24/7.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import (
    TTSEngineNotAvailableError,
    TTSGenerationError,
    VoiceNotFoundError,
)
from announcement_server.tts.engine_base import TTSEngine

logger = logging.getLogger(__name__)


class PiperEngine(TTSEngine):
    """Engine TTS berbasis Piper."""

    def __init__(self, config: TTSConfig) -> None:
        self._binary_path = Path(config.piper_binary_path)
        self._models_dir = Path(config.piper_models_dir)
        self._timeout_seconds = config.generation_timeout_seconds

        # Sengaja TIDAK melempar exception di sini walau binary belum ada.
        # Server tetap harus bisa start & endpoint lain (health, queue)
        # tetap berfungsi normal walau TTS belum terkonfigurasi dengan
        # benar — kegagalan baru terjadi saat item benar-benar diproses
        # (graceful degradation), dan tercatat sebagai warning di log agar
        # operator langsung sadar sejak startup, bukan menunggu komplain
        # user pertama kali memakai /speak.
        if not self._binary_path.is_file():
            logger.warning(
                "Piper binary tidak ditemukan di '%s'. Endpoint /speak akan tetap menerima request, "
                "tetapi item akan berstatus FAILED saat diproses hingga binary tersedia. "
                "Unduh Piper dan set tts.piper_binary_path pada config.yaml.",
                self._binary_path,
            )

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        model_path = self._models_dir / f"{voice}.onnx"
        model_config_path = self._models_dir / f"{voice}.onnx.json"
        if not model_path.exists() or not model_config_path.exists():
            available_voices = (
                sorted(p.stem for p in self._models_dir.glob("*.onnx")) if self._models_dir.exists() else []
            )
            raise VoiceNotFoundError(
                f"Voice '{voice}' tidak ditemukan di '{self._models_dir}'.",
                details={"requested_voice": voice, "available_voices": available_voices},
            )

        # Piper: length_scale lebih besar = bicara lebih LAMBAT. Ini
        # kebalikan dari `speed` (di mana lebih besar = lebih CEPAT),
        # sehingga perlu diinversi di sini.
        length_scale = 1.0 / speed if speed > 0 else 1.0

        with tempfile.TemporaryDirectory(prefix="announcement_tts_") as tmp_dir:
            output_path = Path(tmp_dir) / "output.wav"
            command = [
                str(self._binary_path),
                "--model",
                str(model_path),
                "--output_file",
                str(output_path),
                "--length_scale",
                f"{length_scale:.4f}",
            ]

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise TTSEngineNotAvailableError(
                    f"Piper binary tidak ditemukan di '{self._binary_path}'. Pastikan "
                    "tts.piper_binary_path pada config.yaml sudah benar dan Piper sudah terinstall.",
                ) from exc
            except OSError as exc:
                raise TTSEngineNotAvailableError(f"Gagal menjalankan Piper: {exc}") from exc

            try:
                _stdout, stderr = await asyncio.wait_for(
                    process.communicate(text.encode("utf-8")),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise TTSGenerationError(
                    f"Piper timeout setelah {self._timeout_seconds} detik untuk voice '{voice}'.",
                    details={"voice": voice, "timeout_seconds": self._timeout_seconds},
                ) from exc

            if process.returncode != 0:
                raise TTSGenerationError(
                    f"Piper gagal menghasilkan audio (exit code {process.returncode}).",
                    details={"stderr": stderr.decode("utf-8", errors="replace")[:500]},
                )

            if not output_path.exists():
                raise TTSGenerationError(
                    "Piper melaporkan sukses (exit code 0) tetapi file output tidak ditemukan.",
                )

            return await asyncio.to_thread(output_path.read_bytes)
