"""Model domain untuk Queue System.

Desain keputusan penting:

1. ``QueuePriority`` dibuat sebagai *string* Enum ("urgent"/"high"/dst),
   bukan integer langsung, supaya API lebih terbaca (Swagger menampilkan
   nilai eksplisit) dan client tidak perlu menghafal urutan angka. Bobot
   numerik untuk pengurutan di ``asyncio.PriorityQueue`` didefinisikan
   terpisah di ``queueing.manager`` (single source of truth ada di sana),
   sehingga model tetap murni sebagai representasi data.

2. ``QueueItem`` memakai ``validate_assignment=True`` karena field-nya
   (terutama ``status``) di-mutasi langsung oleh ``QueueManager`` selama
   siklus hidup item (PENDING -> PROCESSING -> COMPLETED/FAILED/CANCELLED).
   Validasi saat assignment mencegah state tidak valid masuk secara tidak
   sengaja pada sistem yang berjalan 24/7.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class QueuePriority(str, Enum):
    """Prioritas pengumuman. Semakin tinggi (URGENT), semakin dulu diproses."""

    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class QueueItemStatus(str, Enum):
    """Status siklus hidup sebuah item antrean."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Status yang dianggap "final" — item tidak akan berubah status lagi setelah ini.
FINISHED_STATUSES: frozenset[QueueItemStatus] = frozenset(
    {QueueItemStatus.COMPLETED, QueueItemStatus.FAILED, QueueItemStatus.CANCELLED}
)


class QueueItem(BaseModel):
    """Representasi satu item pengumuman di dalam antrean."""

    model_config = ConfigDict(validate_assignment=True)

    id: uuid.UUID = Field(description="ID unik item (UUID4)")
    text: str = Field(description="Teks pengumuman")
    priority: QueuePriority = Field(description="Prioritas pengumuman")
    status: QueueItemStatus = Field(description="Status terkini item")
    created_at: datetime = Field(description="Waktu item dibuat (UTC)")
    updated_at: datetime = Field(description="Waktu terakhir status item berubah (UTC)")
    error_message: str | None = Field(default=None, description="Pesan error jika status FAILED")
