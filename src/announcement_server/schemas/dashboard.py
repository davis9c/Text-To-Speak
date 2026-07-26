"""Schema untuk Dashboard API (/status, /history, /metrics — Phase 10).

``StatusResponse.zones`` memakai ulang ``ZoneResponse`` (Phase 6) apa
adanya — field-nya (worker_running, playback_state, current_file,
pending_count, processing_count, device_id, volume) SUDAH mencakup
"Queue, Worker, Device, Zone, Current Audio" yang diminta ROADMAP.md
Phase 10 untuk setiap zone, tanpa duplikasi.

``HistoryItemResponse`` MEWARISI ``QueueItemResponse`` (Phase 2/7) —
menambahkan hanya satu field (``zone``) yang relevan saat riwayat
diagregasi lintas zone, tanpa menduplikasi field lain sama sekali.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from announcement_server.queueing.models import QueueItem
from announcement_server.schemas.queue import QueueItemResponse
from announcement_server.schemas.zones import ZoneResponse


class CacheStatsResponse(BaseModel):
    """Statistik satu direktori cache (TTS atau Announcement Engine)."""

    directory: str = Field(description="Path direktori cache")
    file_count: int = Field(description="Jumlah file yang tersimpan di cache ini")
    total_size_bytes: int = Field(description="Total ukuran seluruh file cache (bytes)")


class StatusResponse(BaseModel):
    """Response body untuk GET /status — snapshot lengkap kondisi server saat ini.

    Mencakup ("Output" sesuai ROADMAP.md Phase 10): Queue, Worker, Cache,
    Device, Zone, Current Audio.
    """

    app_name: str
    version: str
    environment: str
    uptime_seconds: float = Field(description="Lama server berjalan sejak startup terakhir")
    zones: list[ZoneResponse] = Field(
        description="Status seluruh zone (Queue/Worker/Device/Current Audio per zone) — reuse GET /zones (Phase 6)"
    )
    tts_cache: CacheStatsResponse = Field(description="Statistik cache audio hasil sintesis TTS (Phase 3)")
    announcement_cache: CacheStatsResponse = Field(
        description="Statistik cache hasil konversi ffmpeg untuk file audio statis (Phase 7)"
    )
    connected_websocket_clients: int = Field(description="Jumlah client /ws/status yang sedang terhubung (Phase 9)")


class HistoryItemResponse(QueueItemResponse):
    """Satu item riwayat — identik ``QueueItemResponse`` (Phase 2/7) + field ``zone`` (Phase 10)."""

    zone: str = Field(description="Nama zone asal item ini")

    @classmethod
    def from_item(cls, item: QueueItem, *, zone: str, position: int | None = None) -> "HistoryItemResponse":  # type: ignore[override]
        """Reuse ``QueueItemResponse.from_item`` (mapping type/file dari domain) + menambahkan ``zone``."""
        base = QueueItemResponse.from_item(item, position=position)
        return cls(**base.model_dump(), zone=zone)


class HistoryResponse(BaseModel):
    """Response body untuk GET /history."""

    items: list[HistoryItemResponse]
    count: int = Field(description="Jumlah item pada response ini (setelah `limit` diterapkan)")


class MetricsResponse(BaseModel):
    """Response body untuk GET /metrics — ringkasan angka untuk monitoring/dashboard."""

    uptime_seconds: float
    zones_count: int = Field(description="Jumlah zone terdaftar")
    total_items_by_status: dict[str, int] = Field(
        description="Jumlah item per status (pending/processing/completed/failed/cancelled), diagregasi seluruh zone"
    )
    active_schedules_count: int = Field(description="Jumlah jadwal (Phase 8) yang sedang enabled")
    connected_websocket_clients: int = Field(description="Jumlah client /ws/status yang sedang terhubung (Phase 9)")
    tts_cache: CacheStatsResponse
    announcement_cache: CacheStatsResponse
