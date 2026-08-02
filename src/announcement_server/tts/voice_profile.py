"""Voice Profile — representasi voice generic (V2 Phase 4).

Model ini dirancang agar SAMA untuk semua engine TTS (Piper sekarang; Edge
TTS, Azure, ElevenLabs, Coqui nanti). Setiap engine yang mengimplementasikan
``TTSEngine.list_voices()`` mengembalikan daftar ``VoiceProfile`` ini, dan
layer di atasnya (``VoiceRegistry``, dan pemanggil lain di masa depan) hanya
perlu memahami model generic ini — TIDAK PERNAH struktur internal engine
tertentu (mis. nama file ``.onnx`` milik Piper).

Field SENGAJA dibuat opsional untuk metadata yang tidak selalu diketahui
(``language``, ``gender``) alih-alih dipaksa selalu terisi — sebuah engine
boleh saja tidak menyediakan info tersebut, dan pemanggil TIDAK BOLEH
mengarang nilainya (lihat instruksi Phase 4: "Jangan mengarang gender atau
language").
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VoiceProfile(BaseModel):
    """Representasi generic satu voice yang tersedia pada sebuah engine.

    ``id`` unik HANYA dalam lingkup satu ``engine`` (dua engine berbeda boleh
    kebetulan memakai id voice yang sama) — identitas unik global adalah
    pasangan ``(engine, id)``, itulah kenapa ``VoiceRegistry`` mengunci
    berdasarkan pasangan tersebut, bukan ``id`` saja.
    """

    id: str = Field(description="Identifier voice, unik dalam lingkup satu engine (mis. 'en_US-lessac-medium').")
    engine: str = Field(description="Nama engine pemilik voice ini (mis. 'piper'), sesuai nama registrasi di EngineFactory.")
    name: str = Field(description="Nama tampilan voice. Jika engine tidak menyediakan nama terpisah, sama dengan `id`.")
    language: str | None = Field(
        default=None,
        description="Kode bahasa jika benar-benar diketahui dari metadata engine (mis. 'en_US'). "
        "null jika tidak diketahui — TIDAK PERNAH ditebak.",
    )
    gender: str | None = Field(
        default=None,
        description="Gender voice jika benar-benar disediakan oleh metadata engine. "
        "null jika tidak diketahui — TIDAK PERNAH ditebak.",
    )
    source: str = Field(description="Referensi ke sumber/model voice ini (mis. path file model), spesifik per-engine.")
    available: bool = Field(
        default=True,
        description="True jika voice ini benar-benar siap dipakai untuk sintesis saat ini "
        "(mis. seluruh file yang diperlukan lengkap dan dapat diakses).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Info tambahan spesifik-engine yang tidak cukup umum untuk jadi field generic "
        "(mis. sample_rate, jumlah speaker). Boleh kosong.",
    )

    @property
    def registry_key(self) -> tuple[str, str]:
        """Kunci unik (engine, id) yang dipakai VoiceRegistry untuk indexing."""
        return (self.engine, self.id)
