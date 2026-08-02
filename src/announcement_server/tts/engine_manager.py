"""TTS Engine Manager.

Layer di atas ``EngineFactory`` yang menahan (menyimpan) instance engine
yang sudah dibangun dan menyediakan lookup berdasarkan nama, dengan
konsep "default engine" (diambil dari ``tts.engine`` pada config, sama
persis seperti perilaku V1). ``EngineFactory`` TIDAK diganti — manager
ini murni membungkusnya (Decorator sederhana), sehingga menambah engine
baru tetap cukup lewat ``EngineFactory.register()`` tanpa mengubah kelas
ini sama sekali.

V2 Phase 7 — engine tambahan (opt-in): selain engine default, manager ini
sekarang JUGA membangun setiap engine yang disebut di
``tts.additional_engines`` (default kosong ``[]``), memakai
``EngineFactory.build(name, config)``. Ini murni ADITIF dan opt-in —
``TTSConfig`` tanpa ``additional_engines`` (atau dengan list kosong,
default) menghasilkan PERSIS satu engine aktif seperti Phase 2-6, tanpa
perubahan apa pun pada kontrak publik (``get()``/``default_engine_name()``/
``list_engine_names()``). Kegagalan membangun engine TAMBAHAN (mis. karena
alasan internal engine tersebut) TIDAK fatal terhadap startup server —
hanya engine itu yang tidak masuk manager (lihat ``get()`` yang akan
melempar error jelas jika engine tersebut kemudian diminta).

Manager ini SENGAJA tidak berisi logic spesifik engine tertentu (Piper,
eSpeak NG, dst) apa pun — ia hanya tahu tentang nama engine (string) dan
instance ``TTSEngine`` (interface).
"""

from __future__ import annotations

import logging

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import TTSEngineNotAvailableError
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory

logger = logging.getLogger(__name__)


class TTSEngineManager:
    """Menyimpan instance engine yang tersedia dan menyelesaikan pemilihan engine per-request."""

    def __init__(self, config: TTSConfig) -> None:
        self._default_engine_name = config.engine
        # Dibangun eagerly saat startup (sama seperti perilaku V1 —
        # `TTSService.__init__` sebelumnya memanggil `EngineFactory.create(config)`
        # sekali di sini), bukan lazy per-request, supaya kegagalan konstruksi
        # engine default (mis. binary Piper hilang) tetap tercatat sejak awal di
        # log startup seperti sebelumnya. Kegagalan membangun engine DEFAULT tetap
        # fatal (perilaku V1/Phase 2 tidak berubah) -- berbeda dengan engine
        # tambahan di bawah yang sengaja non-fatal.
        self._engines: dict[str, TTSEngine] = {
            self._default_engine_name: EngineFactory.create(config),
        }

        # V2 Phase 7: engine TAMBAHAN (opt-in lewat `tts.additional_engines`,
        # default kosong = TIDAK ADA perubahan perilaku dari Phase 2-6).
        for engine_name in config.additional_engines:
            if engine_name in self._engines:
                continue  # sudah jadi default, tidak perlu dibangun dua kali
            try:
                self._engines[engine_name] = EngineFactory.build(engine_name, config)
            except Exception:
                # Kegagalan membangun engine TAMBAHAN tidak boleh menggagalkan
                # startup server -- Piper (atau engine default lainnya) tetap
                # harus tetap bisa berjalan. Dicatat sebagai warning agar
                # operator tahu sejak startup, sama seperti pola graceful
                # degradation binary hilang pada PiperEngine/EspeakEngine.
                logger.warning(
                    "Gagal membangun engine tambahan '%s' dari tts.additional_engines -- dilewati "
                    "(tidak fatal, engine default '%s' tetap aktif).",
                    engine_name,
                    self._default_engine_name,
                    exc_info=True,
                )

        logger.info(
            "TTSEngineManager siap: default_engine=%s, engine_terdaftar=%s",
            self._default_engine_name,
            sorted(self._engines),
        )

    @property
    def default_engine_name(self) -> str:
        """Nama engine default — diambil dari ``tts.engine`` pada config (perilaku V1, tidak berubah)."""
        return self._default_engine_name

    def list_engine_names(self) -> list[str]:
        """Nama seluruh engine yang saat ini tersedia di manager ini."""
        return sorted(self._engines)

    def get(self, name: str | None = None) -> TTSEngine:
        """Mengambil instance engine berdasarkan nama.

        ``name=None`` (atau tidak diberikan) mengembalikan engine default,
        sehingga pemanggilan lama yang tidak pernah tahu soal multi-engine
        tetap mendapatkan Piper apa adanya (backward compatible dengan V1).

        Raises:
            TTSEngineNotAvailableError: Jika nama engine yang diminta tidak
                dikenali/tidak tersedia di manager ini — TIDAK fallback diam-diam
                ke engine default.
        """
        engine_name = name if name is not None else self._default_engine_name
        engine = self._engines.get(engine_name)
        if engine is None:
            raise TTSEngineNotAvailableError(
                f"Engine TTS '{engine_name}' tidak tersedia pada server ini.",
                details={
                    "requested_engine": engine_name,
                    "available_engines": self.list_engine_names(),
                    "default_engine": self._default_engine_name,
                },
            )
        return engine
