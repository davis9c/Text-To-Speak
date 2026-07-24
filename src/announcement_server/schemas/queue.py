"""Schema untuk endpoint Queue System (/speak, /queue, /clear)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from announcement_server.queueing.models import QueueItem, QueueItemStatus, QueuePriority


class SpeakRequest(BaseModel):
    """Request body untuk POST /speak."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "Nomor antrean A001, silakan menuju loket 3.",
                "priority": "normal",
                "voice": None,
                "speed": 1.0,
                "pitch": 1.0,
                "volume": 1.0,
            }
        }
    )

    text: str = Field(
        min_length=1,
        max_length=1000,
        description="Teks pengumuman yang akan diucapkan (TTS diimplementasikan pada Phase 3)",
    )
    priority: QueuePriority = Field(
        default=QueuePriority.NORMAL,
        description="Prioritas pengumuman: urgent > high > normal > low",
    )
    voice: str | None = Field(
        default=None,
        description="Nama voice/model TTS. Kosongkan (null) untuk memakai default server (tts.default_voice).",
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Kecepatan bicara. 1.0 = normal, <1.0 = lebih lambat, >1.0 = lebih cepat.",
    )
    pitch: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description=(
            "Pitch suara. 1.0 = normal. Catatan: mengubah pitch turut memengaruhi tempo audio "
            "(lihat AudioProcessor.apply_pitch untuk detail keterbatasan teknik yang dipakai)."
        ),
    )
    volume: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Volume relatif. 1.0 = normal, 0.0 = bisu, 2.0 = 2x lebih keras.",
    )


class QueueItemResponse(BaseModel):
    """Response body yang merepresentasikan satu item antrean."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    priority: QueuePriority
    status: QueueItemStatus
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None
    voice: str = Field(description="Voice/model TTS yang dipakai untuk item ini")
    speed: float = Field(description="Kecepatan bicara yang dipakai untuk item ini")
    pitch: float = Field(description="Pitch yang dipakai untuk item ini")
    volume: float = Field(description="Volume yang dipakai untuk item ini")
    audio_file_path: str | None = Field(default=None, description="Path file audio hasil sintesis (terisi setelah selesai)")
    cache_hit: bool | None = Field(default=None, description="True jika audio diambil dari cache TTS")
    position: int | None = Field(
        default=None,
        description="Posisi 1-based di antara item PENDING (1 = akan diproses berikutnya). null jika bukan PENDING.",
    )

    @classmethod
    def from_item(cls, item: QueueItem, *, position: int | None = None) -> "QueueItemResponse":
        """Factory untuk membangun response dari QueueItem domain + posisi opsional."""
        return cls(**item.model_dump(), position=position)


class QueueListResponse(BaseModel):
    """Response body untuk GET /queue."""

    items: list[QueueItemResponse]
    count: int = Field(description="Jumlah item pada response ini")


class ClearResponse(BaseModel):
    """Response body untuk POST /clear."""

    cleared_count: int = Field(description="Jumlah item PENDING yang berhasil dibatalkan")
