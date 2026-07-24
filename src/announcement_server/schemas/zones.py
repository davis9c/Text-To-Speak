"""Schema untuk endpoint Multi Zone (/zones, /zones/{name}, dst — Phase 6).

Endpoint yang menyentuh Queue (``GET /zones/{name}/queue``) dan Playback
(``POST /zones/{name}/device``) SENGAJA memakai ulang schema Phase 2/4
(``QueueListResponse``/``QueueItemResponse`` dari ``schemas/queue.py`` dan
``SelectDeviceRequest``/``PlaybackStatusResponse`` dari
``schemas/playback.py``) — TIDAK diduplikasi di sini.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from announcement_server.playback.models import PlaybackState
from announcement_server.zones.models import Zone


class ZoneCreateRequest(BaseModel):
    """Request body untuk POST /zones."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "lobby",
                "device_id": None,
                "volume": 1.0,
                "enabled": True,
            }
        }
    )

    name: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Nama unik zone (huruf/angka/underscore/dash), dipakai sebagai path segment /zones/{name}/...",
    )
    device_id: int | None = Field(
        default=None,
        description="ID output device untuk zone ini (lihat GET /devices). null = belum ada device dipilih.",
    )
    volume: float = Field(default=1.0, ge=0.0, le=2.0, description="Volume/gain khusus zone ini (0.0 - 2.0)")
    enabled: bool = Field(default=True, description="Jika false, zone dibuat tetapi worker-nya tidak berjalan")
    max_size: int | None = Field(
        default=None, ge=1, description="Override kapasitas antrean zone ini. null = pakai default global (queue.max_size)"
    )
    max_history: int | None = Field(
        default=None,
        ge=0,
        description="Override jumlah riwayat item final zone ini. null = pakai default global (queue.max_history)",
    )
    post_playback_delay_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="Override jeda antar-pengumuman zone ini. null = pakai default global (playback.post_playback_delay_seconds)",
    )


class ZoneUpdateRequest(BaseModel):
    """Request body untuk PUT /zones/{name}. Seluruh field bersifat opsional (pembaruan parsial)."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"enabled": True, "device_id": 2, "volume": 0.8}}
    )

    device_id: int | None = Field(default=None, description="ID output device baru. Kirim null untuk mengosongkan pilihan device.")
    volume: float | None = Field(default=None, ge=0.0, le=2.0, description="Volume/gain baru untuk zone ini (0.0 - 2.0)")
    enabled: bool | None = Field(default=None, description="Aktifkan/nonaktifkan worker zone ini")


class ZoneResponse(BaseModel):
    """Response body yang merepresentasikan satu zone beserta status runtime-nya."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    enabled: bool
    device_id: int | None = None
    volume: float
    created_at: datetime
    updated_at: datetime
    worker_running: bool = Field(description="True jika QueueWorker zone ini sedang berjalan")
    playback_state: PlaybackState | None = Field(
        default=None, description="Status playback saat ini (idle/playing/paused). null jika sistem audio tidak tersedia di server."
    )
    pending_count: int = Field(description="Jumlah item berstatus PENDING pada antrean zone ini")
    processing_count: int = Field(description="Jumlah item berstatus PROCESSING pada antrean zone ini")

    @classmethod
    def build(
        cls,
        zone: Zone,
        *,
        worker_running: bool,
        playback_state: PlaybackState | None,
        pending_count: int,
        processing_count: int,
    ) -> "ZoneResponse":
        return cls(
            **zone.model_dump(),
            worker_running=worker_running,
            playback_state=playback_state,
            pending_count=pending_count,
            processing_count=processing_count,
        )


class ZoneListResponse(BaseModel):
    """Response body untuk GET /zones."""

    zones: list[ZoneResponse]
    count: int = Field(description="Jumlah zone pada response ini")


class ZoneDeleteResponse(BaseModel):
    """Response body untuk DELETE /zones/{name}."""

    name: str = Field(description="Nama zone yang dihapus")
    deleted: bool = Field(default=True, description="Selalu true jika response berhasil dikembalikan (200)")
