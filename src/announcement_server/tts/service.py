"""TTS Service — orkestrator pipeline sintesis TTS.

Ini adalah satu-satunya "pintu masuk" untuk mengubah teks menjadi audio.
Pemanggil (``TTSQueueProcessor`` sekarang; endpoint sinkron apa pun di
masa depan) cukup memanggil ``synthesize()`` tanpa perlu tahu detail
engine, cache, atau post-processing audio.

Alur pipeline:
    1. Hitung cache key (SHA256) dari seluruh parameter.
    2. Jika cache HIT -> kembalikan path file cache langsung (tidak
       memanggil engine sama sekali — inilah manfaat utama cache: server
       yang memutar pengumuman berulang seperti "Nomor antrean A001" tidak
       perlu menjalankan Piper berkali-kali untuk teks yang sama).
    3. Jika cache MISS -> panggil engine untuk sintesis mentah, lalu
       terapkan post-processing volume & pitch, lalu simpan ke cache.
"""

from __future__ import annotations

import logging
from pathlib import Path

from announcement_server.core.config import TTSConfig
from announcement_server.tts.audio_processor import AudioProcessor
from announcement_server.tts.cache import AudioCache
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.models import TTSResult

logger = logging.getLogger(__name__)


class TTSService:
    """Orkestrator pipeline TTS: cache -> engine -> post-processing -> cache."""

    def __init__(self, config: TTSConfig) -> None:
        self._config = config
        self._engine = EngineFactory.create(config)
        self._cache = AudioCache(Path(config.cache_dir))
        self._processor = AudioProcessor()

    async def synthesize(self, *, text: str, voice: str, speed: float, pitch: float, volume: float) -> TTSResult:
        cache_key = AudioCache.compute_key(
            engine=self._config.engine,
            voice=voice,
            text=text,
            speed=speed,
            pitch=pitch,
            volume=volume,
        )

        cached_path = await self._cache.get(cache_key)
        if cached_path is not None:
            logger.info("TTS cache HIT: key=%s voice=%s", cache_key[:12], voice)
            return TTSResult(audio_file_path=str(cached_path), cache_hit=True)

        logger.info("TTS cache MISS: key=%s voice=%s -> memanggil engine '%s'", cache_key[:12], voice, self._config.engine)
        raw_audio = await self._engine.synthesize(text=text, voice=voice, speed=speed)

        processed_audio = self._processor.apply_volume(raw_audio, volume)
        processed_audio = self._processor.apply_pitch(processed_audio, pitch)

        stored_path = await self._cache.put(cache_key, processed_audio)
        return TTSResult(audio_file_path=str(stored_path), cache_hit=False)
