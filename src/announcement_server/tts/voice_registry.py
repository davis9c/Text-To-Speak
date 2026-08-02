"""Voice Registry (V2 Phase 4).

Layer generic yang menahan (menyimpan) daftar ``VoiceProfile`` dari SELURUH
engine yang terdaftar di ``TTSEngineManager``, dikelompokkan per-engine, dan
menyediakan lookup + validasi voice berdasarkan pasangan ``(engine, id)``.

Registry ini SENGAJA tidak mengetahui apa pun soal Piper atau engine
tertentu lainnya — ia hanya memanggil kontrak generic
``TTSEngine.list_voices()`` lewat ``TTSEngineManager``, sama sekali tidak
pernah menyentuh path file, format ``.onnx``, atau detail internal engine
apa pun. Ini adalah pola yang sama dengan ``TTSEngineManager`` sendiri
(Phase 2) dan ``EngineFactory`` (V1) — generic, engine-agnostic.

Catatan scope Phase 4: registry ini adalah *fondasi* saja. Belum ada
endpoint REST yang mengekspornya, dan belum ada wiring otomatis ke
``TTSService``/pipeline sintesis (voice tetap divalidasi oleh engine itu
sendiri saat sintesis, persis seperti V1 -- lihat ``PiperEngine``) supaya
behavior V1 tidak berubah sama sekali. Wiring ke request path adalah
scope phase berikutnya.
"""

from __future__ import annotations

import logging

from announcement_server.tts.engine_manager import TTSEngineManager
from announcement_server.tts.voice_profile import VoiceProfile

logger = logging.getLogger(__name__)


class VoiceRegistry:
    """Menyimpan & menyediakan lookup/validasi voice dari seluruh engine yang terdaftar."""

    def __init__(self) -> None:
        # Key = (engine, voice_id) -- lihat VoiceProfile.registry_key. Dua
        # engine berbeda boleh punya voice dengan id yang kebetulan sama
        # tanpa saling bertabrakan.
        self._voices: dict[tuple[str, str], VoiceProfile] = {}

    @classmethod
    async def create(cls, engine_manager: TTSEngineManager) -> VoiceRegistry:
        """Factory: membuat registry dan langsung memuat voice dari `engine_manager` (refresh awal)."""
        registry = cls()
        await registry.refresh(engine_manager)
        return registry

    async def refresh(self, engine_manager: TTSEngineManager) -> None:
        """Memuat ulang seluruh voice dari seluruh engine yang tersedia di `engine_manager`.

        Menggantikan seluruh isi registry sebelumnya (bukan merge) — memastikan
        voice yang sudah dihapus dari disk/config engine juga hilang dari
        registry, bukan hanya menambahkan voice baru.
        """
        discovered: dict[tuple[str, str], VoiceProfile] = {}
        for engine_name in engine_manager.list_engine_names():
            engine = engine_manager.get(engine_name)
            voices = await engine.list_voices()
            for voice in voices:
                discovered[voice.registry_key] = voice
        self._voices = discovered
        logger.info(
            "VoiceRegistry refresh selesai: %d voice ditemukan dari engine %s",
            len(self._voices),
            engine_manager.list_engine_names(),
        )

    def list_all(self) -> list[VoiceProfile]:
        """Seluruh voice dari seluruh engine, urut berdasarkan (engine, id)."""
        return sorted(self._voices.values(), key=lambda voice: (voice.engine, voice.id))

    def list_by_engine(self, engine: str) -> list[VoiceProfile]:
        """Seluruh voice milik satu engine tertentu, urut berdasarkan id."""
        return sorted(
            (voice for voice in self._voices.values() if voice.engine == engine),
            key=lambda voice: voice.id,
        )

    def get(self, engine: str, voice_id: str) -> VoiceProfile | None:
        """Mencari satu voice berdasarkan (engine, id). Mengembalikan None jika tidak ditemukan."""
        return self._voices.get((engine, voice_id))

    def is_valid(self, engine: str, voice_id: str) -> bool:
        """True hanya jika voice terdaftar DAN berstatus `available` untuk dipakai sintesis."""
        voice = self.get(engine, voice_id)
        return voice is not None and voice.available
