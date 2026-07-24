"""Engine Factory.

Memilih & membangun instance ``TTSEngine`` berdasarkan ``tts.engine`` pada
config. Memakai pola registry sederhana: menambah engine baru (Edge TTS,
Azure, ElevenLabs, Coqui — lihat Phase 15 pada roadmap) di masa depan
cukup dengan memanggil ``EngineFactory.register(nama, builder)``, TANPA
mengubah kelas ``EngineFactory`` maupun ``TTSService`` sama sekali
(Open/Closed Principle).
"""

from __future__ import annotations

from collections.abc import Callable

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import TTSEngineNotAvailableError
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.piper_engine import PiperEngine


class EngineFactory:
    """Factory Pattern: memetakan nama engine (string) ke instance ``TTSEngine``."""

    _registry: dict[str, Callable[[TTSConfig], TTSEngine]] = {}

    @classmethod
    def register(cls, name: str, builder: Callable[[TTSConfig], TTSEngine]) -> None:
        """Mendaftarkan engine baru. Dipanggil sekali per engine saat modul di-import."""
        cls._registry[name] = builder

    @classmethod
    def create(cls, config: TTSConfig) -> TTSEngine:
        """Membangun instance engine sesuai ``config.engine``.

        Raises:
            TTSEngineNotAvailableError: Jika nama engine tidak terdaftar.
        """
        builder = cls._registry.get(config.engine)
        if builder is None:
            raise TTSEngineNotAvailableError(
                f"Engine TTS '{config.engine}' tidak dikenali/terdaftar.",
                details={"requested_engine": config.engine, "available_engines": sorted(cls._registry)},
            )
        return builder(config)


# --- Registrasi engine bawaan -----------------------------------------------
# Engine baru di masa depan (Phase 15) didaftarkan dengan pola yang sama:
#   EngineFactory.register("edge_tts", EdgeTTSEngine)
#   EngineFactory.register("azure", AzureTTSEngine)
EngineFactory.register("piper", PiperEngine)
