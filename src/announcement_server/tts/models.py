"""Model data untuk hasil sintesis TTS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TTSResult:
    """Hasil dari ``TTSService.synthesize()``.

    Dibuat sebagai dataclass (bukan Pydantic model) karena ini murni
    struktur data internal antar layer domain (tts -> queueing), bukan
    payload HTTP yang butuh validasi/serialisasi JSON.
    """

    audio_file_path: str
    """Path absolut/relatif ke file WAV hasil sintesis (baik dari cache maupun baru dibuat)."""

    cache_hit: bool
    """True jika audio diambil dari cache, False jika baru disintesis oleh engine."""
