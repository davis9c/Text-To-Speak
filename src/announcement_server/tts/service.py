"""TTS Service — orkestrator pipeline sintesis TTS.

Ini adalah satu-satunya "pintu masuk" untuk mengubah teks menjadi audio.
Pemanggil (``TTSQueueProcessor`` sekarang; endpoint sinkron apa pun di
masa depan) cukup memanggil ``synthesize()`` tanpa perlu tahu detail
engine, cache, atau post-processing audio.

Alur pipeline:
    1. Selesaikan engine yang dipakai (parameter ``engine`` opsional,
       default ke engine default server — lihat ``TTSEngineManager``).
    2. Hitung cache key (SHA256) dari seluruh parameter, TERMASUK nama
       engine yang sudah diselesaikan di atas.
    3. Jika cache HIT -> kembalikan path file cache langsung (tidak
       memanggil engine sama sekali — inilah manfaat utama cache: server
       yang memutar pengumuman berulang seperti "Nomor antrean A001" tidak
       perlu menjalankan Piper berkali-kali untuk teks yang sama).
    4. Jika cache MISS -> panggil engine untuk sintesis mentah, lalu
       terapkan post-processing volume & pitch, lalu simpan ke cache.
"""

from __future__ import annotations

import logging
from pathlib import Path

from announcement_server.core.config import TTSConfig
from announcement_server.tts.audio_processor import AudioProcessor
from announcement_server.tts.cache import AudioCache
from announcement_server.tts.engine_manager import TTSEngineManager
from announcement_server.tts.models import TTSResult

logger = logging.getLogger(__name__)


class TTSService:
    """Orkestrator pipeline TTS: pilih engine -> cache -> engine -> post-processing -> cache."""

    def __init__(self, config: TTSConfig, *, engine_manager: TTSEngineManager | None = None) -> None:
        self._config = config
        # `engine_manager` bersifat opsional (dependency injection untuk test) —
        # perilaku default (tidak diberikan) membangun TTSEngineManager dari
        # `config` apa adanya, identik dengan `EngineFactory.create(config)`
        # langsung seperti pada V1.
        self._engine_manager = engine_manager if engine_manager is not None else TTSEngineManager(config)
        self._cache = AudioCache(Path(config.cache_dir))
        self._processor = AudioProcessor()

    @property
    def engine_manager(self) -> TTSEngineManager:
        """Akses read-only ke TTSEngineManager (V2 Phase 5 — dipakai endpoint discovery
        `GET /tts/engines` & `GET /tts/voices/*`). TIDAK dipakai oleh pipeline sintesis
        itu sendiri (`synthesize()` di bawah sudah punya akses langsung lewat `self._engine_manager`)."""
        return self._engine_manager

    async def synthesize(
        self, *, text: str, voice: str, speed: float, pitch: float, volume: float, engine: str | None = None
    ) -> TTSResult:
        """Mensintesis teks menjadi audio.

        ``engine=None`` (default, perilaku V1) memakai engine default server
        (``TTSEngineManager.default_engine_name``, yaitu ``tts.engine`` pada
        config). Jika ``engine`` diberikan tetapi tidak tersedia,
        ``TTSEngineNotAvailableError`` dilempar SEBELUM cache disentuh sama
        sekali — TIDAK ada fallback diam-diam ke engine default.
        """
        tts_engine = self._engine_manager.get(engine)
        resolved_engine_name = engine if engine is not None else self._engine_manager.default_engine_name

        effective_voice = voice or self._config.default_voice

        cache_key = AudioCache.compute_key(
            engine=resolved_engine_name,
            voice=effective_voice,
            text=text,
            speed=speed,
            pitch=pitch,
            volume=volume,
        )

        cached_path = await self._cache.get(cache_key)
        if cached_path is not None:
            logger.info("TTS cache HIT: key=%s voice=%s engine=%s", cache_key[:12], effective_voice, resolved_engine_name)
            return TTSResult(audio_file_path=str(cached_path), cache_hit=True)

        # Jaring pengaman default voice (hanya untuk voice DEFAULT server, bukan voice
        # yang diminta eksplisit): jika `tts.default_voice` pada config tidak tersedia
        # di engine (mis. model belum diunduh / nama salah), fallback ke voice pertama
        # yang benar-benar tersedia agar request tanpa `voice` tetap berhasil — dengan
        # peringatan jelas di log. Request dengan `voice` EKSPLISIT tetap gagal dengan
        # VoiceNotFoundError (semantik terdokumentasi tidak berubah).
        if effective_voice == self._config.default_voice:
            try:
                available = [v for v in await tts_engine.list_voices() if v.available]
            except Exception as exc:  # noqa: BLE001 — discovery gagal tidak boleh mematikan sintesis
                logger.warning("Voice discovery gagal saat fallback default voice: %s", exc)
                available = []
            if available and not any(v.id == effective_voice for v in available):
                fallback_voice = available[0].id
                logger.warning(
                    "default_voice '%s' tidak tersedia di engine '%s' — fallback ke voice '%s'. "
                    "Perbaiki tts.default_voice pada config.yaml agar memakai voice yang diinginkan.",
                    effective_voice,
                    resolved_engine_name,
                    fallback_voice,
                )
                effective_voice = fallback_voice
                cache_key = AudioCache.compute_key(
                    engine=resolved_engine_name,
                    voice=effective_voice,
                    text=text,
                    speed=speed,
                    pitch=pitch,
                    volume=volume,
                )
                cached_path = await self._cache.get(cache_key)
                if cached_path is not None:
                    logger.info(
                        "TTS cache HIT (voice fallback): key=%s voice=%s engine=%s",
                        cache_key[:12],
                        effective_voice,
                        resolved_engine_name,
                    )
                    return TTSResult(audio_file_path=str(cached_path), cache_hit=True)

        logger.info(
            "TTS cache MISS: key=%s voice=%s -> memanggil engine '%s'", cache_key[:12], effective_voice, resolved_engine_name
        )
        raw_audio = await tts_engine.synthesize(text=text, voice=effective_voice, speed=speed)

        processed_audio = self._processor.apply_volume(raw_audio, volume)
        processed_audio = self._processor.apply_pitch(processed_audio, pitch)

        stored_path = await self._cache.put(cache_key, processed_audio)
        return TTSResult(audio_file_path=str(stored_path), cache_hit=False)

    async def get_cache_stats(self) -> tuple[int, int]:
        """Mengembalikan ``(jumlah_file, total_ukuran_bytes)`` cache TTS saat ini (Phase 10 — Dashboard API)."""
        return await self._cache.get_stats()

    async def cleanup_cache(self, *, max_age_days: float | None = None) -> tuple[int, int]:
        """Membersihkan cache TTS lebih tua dari ``max_age_days`` (Phase 14).

        ``max_age_days=None`` (default) memakai ``tts.cache_max_age_days`` dari config.
        """
        effective_max_age = max_age_days if max_age_days is not None else self._config.cache_max_age_days
        return await self._cache.cleanup(max_age_days=effective_max_age)
