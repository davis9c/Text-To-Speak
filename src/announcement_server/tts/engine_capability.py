"""Engine Capability (V2 Phase 7).

Model generic untuk mengiklankan kapabilitas satu engine -- MURNI
informasional untuk saat ini. TTSService/pipeline sintesis TIDAK membaca
field ini sama sekali (kontrak ``TTSEngine.synthesize(text, voice, speed)``
tidak berubah -- lihat catatan Phase 3: volume/pitch tetap post-processing
generic lewat ``AudioProcessor`` untuk SEMUA engine, terlepas dari apakah
engine tersebut punya dukungan native atau tidak). Field ini disediakan
sebagai fondasi untuk phase mendatang yang mungkin memanfaatkan kapabilitas
native secara nyata.

Catatan audit: sebelum V2 Phase 7, tidak ada "Engine Capability" apa pun di
codebase (dikonfirmasi lewat pencarian menyeluruh) meskipun disebut sebagai
prasyarat Phase 7 -- modul ini adalah fondasi minimal yang baru dibuat di
phase ini, mengikuti pola non-breaking yang sama dengan ``VoiceProfile``
(Phase 4): default method di ``TTSEngine`` (bukan abstractmethod) agar
seluruh test-double ``TTSEngine`` yang sudah ada tetap valid tanpa
perubahan.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EngineCapability(BaseModel):
    """Kapabilitas satu TTS engine (tidak menyertakan nama engine -- pemanggil yang
    tahu engine mana yang ditanyakan, mis. lewat TTSEngineManager.get(name))."""

    supports_speed: bool = Field(
        default=True, description="True jika engine punya mekanisme native untuk mengatur kecepatan bicara."
    )
    supports_native_pitch: bool = Field(
        default=False,
        description="True jika engine punya mekanisme native untuk mengatur pitch. Jika False, pitch tetap "
        "diterapkan lewat post-processing generic (AudioProcessor) seperti biasa -- lihat TTSService.",
    )
    supports_native_volume: bool = Field(
        default=False,
        description="True jika engine punya mekanisme native untuk mengatur volume. Jika False, volume tetap "
        "diterapkan lewat post-processing generic (AudioProcessor) seperti biasa -- lihat TTSService.",
    )
    supports_ssml: bool = Field(default=False, description="True jika engine menerima input berformat SSML.")
    offline: bool = Field(
        default=True, description="True jika engine berjalan sepenuhnya lokal tanpa memerlukan layanan cloud."
    )
    max_text_length: int | None = Field(
        default=None, description="Batas panjang teks per-permintaan jika benar-benar didokumentasikan oleh engine. "
        "null jika tidak ada batas yang diketahui -- tidak pernah ditebak.",
    )
    native_sample_rate: int | None = Field(
        default=None,
        description="Sample rate native jika seragam untuk seluruh voice engine ini. null jika bervariasi "
        "per-voice atau tidak diketahui -- tidak pernah ditebak.",
    )
