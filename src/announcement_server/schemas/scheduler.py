"""Schema untuk endpoint Scheduler (/scheduler — Phase 8).

``announcement`` pada request body SENGAJA memakai ulang ``SpeakRequest``
(Phase 2/7, ``schemas/queue.py``) apa adanya — field-nya (``type``,
``text``, ``file``, ``priority``, ``voice``, ``speed``, ``pitch``,
``volume``) dan validator konsistensi ``type`` vs ``text``/``file`` PERSIS
sama dengan yang dibutuhkan satu jadwal, sehingga tidak perlu
diduplikasi. Response ``announcement`` memakai ulang ``AnnouncementSpec``
(domain, ``scheduler/models.py``) — murni data, aman diekspos langsung.

Endpoint ``POST /scheduler/{id}/trigger`` memakai ulang
``QueueItemResponse`` (Phase 2/7) sebagai response body-nya (hasil
trigger identik dengan hasil ``POST /speak``: satu item baru masuk
antrean) — juga tanpa duplikasi.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from announcement_server.scheduler.models import AnnouncementSpec, ScheduleRecurrence
from announcement_server.schemas.queue import SpeakRequest


class ScheduleCreateRequest(BaseModel):
    """Request body untuk POST /scheduler."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Bell Masuk",
                    "zone": "main",
                    "recurrence": "daily",
                    "time_of_day": "07:00",
                    "announcement": {"type": "audio", "file": "sounds/bell.mp3", "priority": "high"},
                },
                {
                    "name": "Istirahat",
                    "zone": "main",
                    "recurrence": "weekly",
                    "time_of_day": "12:00",
                    "days_of_week": [0, 1, 2, 3, 4],
                    "announcement": {"type": "tts", "text": "Waktunya istirahat siang."},
                },
            ]
        }
    )

    name: str = Field(min_length=1, max_length=100, description="Label jadwal, mis. 'Bell Masuk'")
    enabled: bool = Field(default=True, description="Jika false, jadwal terdaftar tapi tidak akan pernah terpicu")
    zone: str = Field(default="main", description="Nama zone tujuan pengumuman (lihat GET /zones)")
    recurrence: ScheduleRecurrence = Field(description="'daily' | 'weekly' | 'once'")
    time_of_day: time = Field(description="Jam pemicu, format 'HH:MM' atau 'HH:MM:SS' (24 jam)")
    days_of_week: list[int] | None = Field(
        default=None,
        description="WAJIB untuk recurrence='weekly': daftar hari (0=Senin .. 6=Minggu). Diabaikan untuk recurrence lain.",
    )
    run_date: date | None = Field(
        default=None, description="WAJIB untuk recurrence='once', format 'YYYY-MM-DD'. Diabaikan untuk recurrence lain."
    )
    announcement: SpeakRequest = Field(description="Isi pengumuman yang akan di-enqueue saat jadwal terpicu")


class ScheduleUpdateRequest(BaseModel):
    """Request body untuk PUT /scheduler/{id}. Seluruh field opsional (pembaruan parsial)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    zone: str | None = None
    recurrence: ScheduleRecurrence | None = None
    time_of_day: time | None = None
    days_of_week: list[int] | None = None
    run_date: date | None = None
    announcement: SpeakRequest | None = None


class ScheduleResponse(BaseModel):
    """Response body yang merepresentasikan satu jadwal."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    enabled: bool
    zone: str
    recurrence: ScheduleRecurrence
    time_of_day: time
    days_of_week: list[int] | None = None
    run_date: date | None = None
    announcement: AnnouncementSpec
    last_triggered_at: datetime | None = None
    next_run_at: datetime | None = Field(
        default=None, description="Waktu pemicu berikutnya. null jika jadwal 'once' sudah pernah terpicu."
    )
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(BaseModel):
    """Response body untuk GET /scheduler."""

    schedules: list[ScheduleResponse]
    count: int = Field(description="Jumlah jadwal pada response ini")


class ScheduleDeleteResponse(BaseModel):
    """Response body untuk DELETE /scheduler/{id}."""

    id: uuid.UUID
    deleted: bool = Field(default=True, description="Selalu true jika response berhasil dikembalikan (200)")
