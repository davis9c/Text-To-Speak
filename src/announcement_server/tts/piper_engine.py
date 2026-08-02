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
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import (
    TTSEngineNotAvailableError,
    TTSGenerationError,
    VoiceNotFoundError,
)
from announcement_server.core.retry import retry_with_backoff
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_capability import EngineCapability
from announcement_server.tts.voice_profile import VoiceProfile

logger = logging.getLogger(__name__)


class PiperEngine(TTSEngine):
    """Engine TTS berbasis Piper."""

    def __init__(self, config: TTSConfig) -> None:
        self._binary_path = Path(config.piper_binary_path)
        self._models_dir = Path(config.piper_models_dir)
        self._timeout_seconds = config.generation_timeout_seconds
        self._max_retries = config.max_retries
        self._retry_backoff_seconds = config.retry_backoff_seconds

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
        # Retry (Phase 14) hanya untuk TTSGenerationError (kegagalan proses Piper yang
        # transien, mis. exit code non-zero sesaat) — TTSEngineNotAvailableError (binary
        # tidak ada) dan VoiceNotFoundError (model tidak ada) TIDAK di-retry karena
        # mengulang tidak akan mengubah hasil (kegagalan permanen).
        return await retry_with_backoff(
            lambda: self._synthesize_once(text=text, voice=voice, speed=speed),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
            retry_on=(TTSGenerationError,),
            operation_name=f"Piper synthesize(voice={voice})",
        )

    async def _synthesize_once(self, *, text: str, voice: str, speed: float) -> bytes:
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

    async def list_voices(self) -> list[VoiceProfile]:
        """Voice Discovery Piper (V2 Phase 4).

        Men-scan ``piper_models_dir`` secara langsung dan memasangkan setiap
        ``<voice>.onnx`` dengan ``<voice>.onnx.json`` — mekanisme yang SAMA
        PERSIS dengan resolusi voice yang dipakai ``_synthesize_once()`` di
        atas saat sintesis sesungguhnya. TIDAK ADA daftar voice yang
        di-hardcode di mana pun; seluruhnya berasal dari isi direktori model
        yang sesungguhnya ada di disk.

        Metadata (``language``) hanya diisi jika BENAR-BENAR ada di file
        config voice (``<voice>.onnx.json``) — format config Piper resmi
        menyertakan ``language.code`` (mis. ``"en_US"``) tetapi TIDAK
        menyertakan info gender sama sekali, sehingga ``gender`` SELALU
        ``None`` untuk voice Piper (bukan ditebak/dihilangkan secara acak).
        """
        return await asyncio.to_thread(self._discover_voices_sync)

    def _discover_voices_sync(self) -> list[VoiceProfile]:
        if not self._models_dir.exists():
            return []

        voices: list[VoiceProfile] = []
        for onnx_path in sorted(self._models_dir.glob("*.onnx")):
            voice_id = onnx_path.stem
            config_path = self._models_dir / f"{voice_id}.onnx.json"
            config_exists = config_path.exists()

            language: str | None = None
            metadata: dict[str, Any] = {}
            if config_exists:
                try:
                    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "Gagal membaca metadata voice '%s' di '%s': %s -- voice tetap didaftarkan "
                        "tanpa metadata bahasa.",
                        voice_id,
                        config_path,
                        exc,
                    )
                    raw_config = {}

                # Hanya membaca field yang MEMANG ada pada file config Piper --
                # tidak pernah menebak/mengarang bahasa (lihat instruksi Phase 4).
                language_info = raw_config.get("language")
                if isinstance(language_info, dict):
                    language_code = language_info.get("code")
                    if isinstance(language_code, str):
                        language = language_code
                    language_name = language_info.get("name_english")
                    if isinstance(language_name, str):
                        metadata["language_name"] = language_name

                audio_info = raw_config.get("audio")
                if isinstance(audio_info, dict) and isinstance(audio_info.get("sample_rate"), int):
                    metadata["sample_rate"] = audio_info["sample_rate"]

                if isinstance(raw_config.get("num_speakers"), int):
                    metadata["num_speakers"] = raw_config["num_speakers"]

            voices.append(
                VoiceProfile(
                    id=voice_id,
                    engine="piper",
                    name=voice_id,
                    language=language,
                    gender=None,  # Format config Piper tidak menyediakan info gender -- tidak diarang.
                    source=str(onnx_path),
                    # `available=False` jika config JSON-nya hilang: `_synthesize_once()` di atas
                    # akan menolak voice ini dengan VoiceNotFoundError, jadi discovery HARUS
                    # melaporkan status yang konsisten dengan perilaku sintesis sesungguhnya.
                    available=config_exists,
                    metadata=metadata,
                )
            )
        return voices

    async def get_capability(self) -> EngineCapability:
        """Kapabilitas Piper (V2 Phase 7): hanya `--length_scale` (speed) yang native --
        tidak ada flag pitch/volume native pada CLI Piper, keduanya tetap post-processing
        generic (lihat audit Phase 3: `speed -> --length_scale` di PiperEngine,
        volume/pitch selalu lewat `AudioProcessor` generic di `TTSService`)."""
        return EngineCapability(
            supports_speed=True,
            supports_native_pitch=False,
            supports_native_volume=False,
            supports_ssml=False,
            offline=True,
            max_text_length=None,  # Piper tidak mendokumentasikan batas panjang teks tetap -- tidak ditebak.
            native_sample_rate=None,  # Bervariasi per-voice (lihat metadata sample_rate di list_voices()).
        )
