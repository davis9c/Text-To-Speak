"""Engine Factory.

Memilih & membangun instance ``TTSEngine`` berdasarkan ``tts.engine`` pada
config. Memakai pola registry sederhana: menambah engine baru (Edge TTS,
Azure, ElevenLabs — lihat roadmap) di masa depan cukup dengan memanggil
``EngineFactory.register(nama, builder)``, TANPA mengubah kelas
``EngineFactory`` maupun ``TTSService`` sama sekali (Open/Closed Principle).

V2 Phase 7 menambahkan ``build(name, config)`` dan ``list_registered_names()``
-- keduanya murni ADITIF (``register``/``create`` tidak berubah perilaku
sama sekali) -- dibutuhkan ``TTSEngineManager`` untuk membangun engine
TAMBAHAN (``tts.additional_engines``) selain engine default, memakai
``TTSConfig`` yang sama tanpa perlu tahu detail internal engine mana pun.
"""

from __future__ import annotations

from collections.abc import Callable

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import TTSEngineNotAvailableError
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.espeak_engine import EspeakEngine
from announcement_server.tts.piper_engine import PiperEngine
from announcement_server.tts.styletts2_engine import StyleTTS2Engine


class EngineFactory:
    """Factory Pattern: memetakan nama engine (string) ke instance ``TTSEngine``."""

    _registry: dict[str, Callable[[TTSConfig], TTSEngine]] = {}

    @classmethod
    def register(cls, name: str, builder: Callable[[TTSConfig], TTSEngine]) -> None:
        """Mendaftarkan engine baru. Dipanggil sekali per engine saat modul di-import."""
        cls._registry[name] = builder

    @classmethod
    def create(cls, config: TTSConfig) -> TTSEngine:
        """Membangun instance engine sesuai ``config.engine`` (engine default/utama).

        Raises:
            TTSEngineNotAvailableError: Jika nama engine tidak terdaftar.
        """
        return cls.build(config.engine, config)

    @classmethod
    def build(cls, name: str, config: TTSConfig) -> TTSEngine:
        """Membangun instance engine berdasarkan nama EKSPLISIT (V2 Phase 7).

        Berbeda dengan ``create()`` (yang selalu memakai ``config.engine``),
        ``build()`` menerima nama engine secara eksplisit -- dipakai
        ``TTSEngineManager`` untuk membangun engine TAMBAHAN
        (``tts.additional_engines``) dengan ``TTSConfig`` yang sama persis
        (setiap builder engine memilih sendiri field mana yang relevan
        untuknya, lihat catatan isolasi konfigurasi di ``core/config.py``).

        Raises:
            TTSEngineNotAvailableError: Jika nama engine tidak terdaftar.
        """
        builder = cls._registry.get(name)
        if builder is None:
            raise TTSEngineNotAvailableError(
                f"Engine TTS '{name}' tidak dikenali/terdaftar.",
                details={"requested_engine": name, "available_engines": sorted(cls._registry)},
            )
        return builder(config)

    @classmethod
    def list_registered_names(cls) -> list[str]:
        """Nama seluruh engine yang terdaftar di EngineFactory (V2 Phase 7) -- TIDAK sama
        dengan engine yang AKTIF di satu server (lihat ``TTSEngineManager.list_engine_names()``);
        ini adalah seluruh engine yang MUNGKIN diaktifkan, terlepas dari config server saat ini."""
        return sorted(cls._registry)


# --- Registrasi engine bawaan -----------------------------------------------
# Engine baru di masa depan didaftarkan dengan pola yang sama:
#   EngineFactory.register("edge_tts", EdgeTTSEngine)
#   EngineFactory.register("azure", AzureTTSEngine)
EngineFactory.register("piper", PiperEngine)
EngineFactory.register("espeak", EspeakEngine)
EngineFactory.register("styletts2", StyleTTS2Engine)
