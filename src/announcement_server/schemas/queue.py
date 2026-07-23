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
