"""Schema untuk endpoint Audio Playback (/devices, /device, /pause, /resume, /stop)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from announcement_server.playback.models import PlaybackState


class AudioDeviceResponse(BaseModel):
    """Representasi satu output audio device."""

    id: int = Field(description="ID device, dipakai pada POST /device")
    name: str = Field(description="Nama device seperti dikenali Windows (mis. 'Speaker (Realtek Audio)')")
    max_output_channels: int = Field(description="Jumlah channel output maksimum (1=mono, 2=stereo, dst)")
    default_samplerate: float = Field(description="Sample rate default device (Hz)")
    is_default: bool = Field(description="True jika ini adalah default output device sistem Windows")


class DeviceListResponse(BaseModel):
    """Response body untuk GET /devices."""

    devices: list[AudioDeviceResponse]
    count: int = Field(description="Jumlah output device yang ditemukan")


class SelectDeviceRequest(BaseModel):
    """Request body untuk POST /device."""

    device_id: int = Field(description="ID device output yang dipilih, ambil dari hasil GET /devices")


class PlaybackStatusResponse(BaseModel):
    """Response body yang dikembalikan oleh POST /device, /pause, /resume, /stop."""

    state: PlaybackState = Field(description="Status playback saat ini: idle | playing | paused")
    current_file: str | None = Field(default=None, description="Path file audio yang sedang/terakhir diputar")
    selected_device_id: int | None = Field(default=None, description="ID output device yang sedang dipilih")
