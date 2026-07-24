"""Router: Audio Playback (Phase 4).

Endpoint di sini murni kontrol layer Audio Playback yang independen —
TIDAK terhubung otomatis ke Queue System/TTS Engine. Menyambungkan hasil
TTS ke playback secara otomatis per item antrean adalah scope Phase 5.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, status

from announcement_server.api.deps import AudioDeviceManagerDep, PlaybackManagerDep
from announcement_server.schemas.playback import (
    AudioDeviceResponse,
    DeviceListResponse,
    PlaybackStatusResponse,
    SelectDeviceRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Playback"])


def _status_response(playback_manager: PlaybackManagerDep) -> PlaybackStatusResponse:
    return PlaybackStatusResponse(
        state=playback_manager.state,
        current_file=playback_manager.current_file,
        selected_device_id=playback_manager.selected_device_id,
    )


@router.get(
    "/devices",
    response_model=DeviceListResponse,
    summary="Melihat daftar output audio device yang tersedia",
    description="Menampilkan seluruh output device yang dikenali Windows (speaker, headphone, sound card TOA, dsb).",
)
async def get_devices(device_manager: AudioDeviceManagerDep) -> DeviceListResponse:
    devices = device_manager.list_output_devices()
    return DeviceListResponse(
        # `AudioDevice` (playback/models.py) sengaja didefinisikan sebagai
        # `@dataclass(frozen=True, slots=True)` untuk efisiensi memori — akibatnya
        # objeknya TIDAK punya `__dict__` (beda dengan dataclass biasa). Memakai
        # `dataclasses.asdict()` (introspeksi lewat `fields()`, bukan `__dict__`)
        # supaya tetap berfungsi benar terlepas dari `slots=True`.
        devices=[AudioDeviceResponse(**asdict(device)) for device in devices],
        count=len(devices),
    )


@router.post(
    "/device",
    response_model=PlaybackStatusResponse,
    summary="Memilih output device aktif untuk playback",
    description="ID device diambil dari hasil GET /devices. Tidak menghentikan playback yang sedang berjalan.",
)
async def select_device(payload: SelectDeviceRequest, playback_manager: PlaybackManagerDep) -> PlaybackStatusResponse:
    playback_manager.select_device(payload.device_id)
    return _status_response(playback_manager)


@router.post(
    "/pause",
    response_model=PlaybackStatusResponse,
    summary="Menjeda playback yang sedang berjalan",
    description="Mengembalikan error 409 jika tidak sedang ada playback yang berjalan (state != playing).",
)
async def pause_playback(playback_manager: PlaybackManagerDep) -> PlaybackStatusResponse:
    playback_manager.pause()
    return _status_response(playback_manager)


@router.post(
    "/resume",
    response_model=PlaybackStatusResponse,
    summary="Melanjutkan playback yang sedang dijeda",
    description="Mengembalikan error 409 jika tidak sedang dijeda (state != paused).",
)
async def resume_playback(playback_manager: PlaybackManagerDep) -> PlaybackStatusResponse:
    playback_manager.resume()
    return _status_response(playback_manager)


@router.post(
    "/stop",
    response_model=PlaybackStatusResponse,
    summary="Menghentikan playback sepenuhnya",
    description="Idempotent — aman dipanggil walau tidak ada playback yang sedang berjalan.",
    status_code=status.HTTP_200_OK,
)
async def stop_playback(playback_manager: PlaybackManagerDep) -> PlaybackStatusResponse:
    await playback_manager.stop()
    return _status_response(playback_manager)
