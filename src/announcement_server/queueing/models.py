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


class AnnouncementType(str, Enum):
    """Sumber audio satu item pengumuman (Phase 7 — Announcement Engine).

    - ``TTS`` (default, perilaku Phase 1-6 tanpa perubahan): teks disintesis
      lewat ``TTSService`` (Phase 3).
    - ``AUDIO``: memutar file audio yang SUDAH ADA di disk (bell, alarm,
      jingle, MP3/WAV apa pun) — TIDAK melalui TTS sama sekali, lihat
      ``announcement/asset_resolver.py``.
    """

    TTS = "tts"
    AUDIO = "audio"


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

# Status default yang ditampilkan saat parameter `status` tidak diberikan pada
# endpoint listing queue (GET /queue sejak Phase 2, GET /zones/{name}/queue
# sejak Phase 6) — hanya item yang masih "aktif" (belum final). Didefinisikan
# di sini (bukan duplikat literal di setiap router) supaya kedua endpoint
# selalu konsisten satu sama lain.
DEFAULT_ACTIVE_STATUSES: frozenset[QueueItemStatus] = frozenset(
    {QueueItemStatus.PENDING, QueueItemStatus.PROCESSING}
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

    # --- Field TTS (Phase 3) ---
    # Disimpan per-item (bukan hanya di request) karena item terus ada di
    # registry setelah request selesai, dan worker (berjalan async, terpisah
    # dari request/response HTTP) butuh parameter ini saat memprosesnya nanti.
    engine: str | None = Field(
        default=None,
        description="Nama TTS engine yang dipakai untuk item ini (mis. 'piper'). "
        "null = pakai engine default server (perilaku V1, tidak berubah). Diabaikan jika announcement_type='audio'.",
    )
    voice: str = Field(default="default", description="Voice/model TTS yang dipakai untuk item ini")
    speed: float = Field(default=1.0, description="Kecepatan bicara yang dipakai untuk item ini")
    pitch: float = Field(default=1.0, description="Pitch yang dipakai untuk item ini")
    volume: float = Field(default=1.0, description="Volume yang dipakai untuk item ini")
    audio_file_path: str | None = Field(
        default=None, description="Path file audio hasil sintesis. Terisi setelah TTS selesai diproses."
    )
    cache_hit: bool | None = Field(
        default=None, description="True jika audio diambil dari cache, False jika baru disintesis. None jika belum diproses."
    )

    # --- Field Announcement Engine (Phase 7) ---
    # `announcement_type` menentukan tahap "Cache/Generate" mana yang
    # dipakai (lihat `announcement/source_processor.py`): TTS (Phase 3,
    # tidak diubah) atau resolusi file audio statis (Phase 7). Default
    # `TTS` menjaga SELURUH item lama (Phase 1-6, tidak pernah mengirim
    # field ini) berperilaku identik seperti sebelumnya.
    announcement_type: AnnouncementType = Field(
        default=AnnouncementType.TTS, description="Sumber audio item ini: 'tts' (default) atau 'audio'"
    )
    source_file: str | None = Field(
        default=None,
        description="Path file audio statis (relatif terhadap announcement.sounds_dir) untuk "
        "announcement_type='audio'. null untuk announcement_type='tts'.",
    )
