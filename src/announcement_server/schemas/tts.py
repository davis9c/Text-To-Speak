"""Schema response untuk TTS Engine & Voice Discovery API (V2 Phase 5).

Model di sini SENGAJA generic dan hanya mengekspos informasi yang aman untuk
klien publik (HTML Client V2) -- tidak ada path binary, path model, atau
detail konfigurasi server. Field-nya diambil dari ``TTSEngineManager``
(engine) dan ``VoiceProfile``/``VoiceRegistry`` (voice), tidak pernah dari
implementasi engine tertentu secara langsung.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from announcement_server.tts.engine_capability import EngineCapability
from announcement_server.tts.voice_profile import VoiceProfile


class EngineInfo(BaseModel):
    """Informasi publik satu TTS engine (aman ditampilkan ke klien)."""

    id: str = Field(description="Nama/identifier engine, sesuai nama registrasi di EngineFactory (mis. 'piper').")
    display_name: str = Field(description="Nama tampilan engine (turunan generic dari `id`, bukan hardcoded per-engine).")
    is_default: bool = Field(description="True jika ini adalah engine default server saat ini (dari `tts.engine`).")
    available: bool = Field(
        description="True jika engine ini berhasil diinisialisasi dan siap dipakai oleh TTSEngineManager."
    )
    capability: EngineCapability = Field(
        description="Kapabilitas native engine ini (V2 Phase 7) -- murni informasional, lihat EngineCapability."
    )


class EngineListResponse(BaseModel):
    """Response untuk GET /tts/engines."""

    engines: list[EngineInfo]
    default_engine: str = Field(description="Nama engine default server saat ini.")


class VoiceInfo(BaseModel):
    """Informasi publik satu voice (aman ditampilkan ke klien -- TIDAK menyertakan
    field `source` milik VoiceProfile, karena itu adalah detail internal seperti
    path file model yang spesifik per-engine)."""

    id: str = Field(description="Identifier voice, unik dalam lingkup satu engine.")
    engine: str = Field(description="Nama engine pemilik voice ini.")
    name: str = Field(description="Nama tampilan voice.")
    language: str | None = Field(default=None, description="Kode bahasa jika diketahui dari metadata engine, mis. 'en_US'.")
    gender: str | None = Field(default=None, description="Gender voice jika diketahui dari metadata engine.")
    available: bool = Field(description="True jika voice ini siap dipakai untuk sintesis saat ini.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Info tambahan spesifik-engine (mis. sample_rate).")

    @classmethod
    def from_voice_profile(cls, profile: VoiceProfile) -> VoiceInfo:
        """Memetakan VoiceProfile (internal, punya field `source`) ke VoiceInfo (publik)."""
        return cls(
            id=profile.id,
            engine=profile.engine,
            name=profile.name,
            language=profile.language,
            gender=profile.gender,
            available=profile.available,
            metadata=profile.metadata,
        )


class VoiceListResponse(BaseModel):
    """Response untuk GET /tts/voices dan GET /tts/voices/{engine}."""

    voices: list[VoiceInfo]
    count: int = Field(description="Jumlah voice pada `voices` (kemudahan untuk klien, setara len(voices)).")
