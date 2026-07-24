"""Dependency Injection providers.

Semua dependency yang dipakai lintas router didefinisikan di sini agar
mudah di-override saat testing (``app.dependency_overrides[...] = ...``)
dan agar router tidak melakukan instansiasi objek secara langsung
(sesuai prinsip Dependency Inversion).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from announcement_server.core.config import AppSettings, get_settings
from announcement_server.core.exceptions import PlaybackDeviceError
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.playback.manager import PlaybackManager
from announcement_server.queueing.manager import QueueManager
from announcement_server.zones.manager import ZoneManager

# Alias tipe untuk dipakai di signature endpoint, mis:
#   async def health(settings: SettingsDep): ...
SettingsDep = Annotated[AppSettings, Depends(get_settings)]


def get_queue_manager(request: Request) -> QueueManager:
    """Mengambil instance QueueManager tunggal yang dibuat saat app startup.

    QueueManager disimpan di ``app.state`` (bukan lewat ``lru_cache`` seperti
    settings) karena instance-nya menyimpan state mutable (registry item +
    asyncio.PriorityQueue) yang harus sama persis dengan yang dikonsumsi
    oleh QueueWorker — instance ini dibuat sekali di ``lifespan`` (main.py)
    dan tidak boleh dibuat ulang setiap request.
    """
    return request.app.state.queue_manager


# Alias tipe untuk dipakai di signature endpoint, mis:
#   async def speak(request: SpeakRequest, manager: QueueManagerDep): ...
QueueManagerDep = Annotated[QueueManager, Depends(get_queue_manager)]


def get_audio_device_manager(request: Request) -> AudioDeviceManager:
    """Mengambil instance AudioDeviceManager tunggal (dibuat saat app startup).

    Bisa bernilai ``None`` di ``app.state`` jika PortAudio/driver audio
    gagal terdeteksi saat startup (lihat ``main.py`` lifespan) — dalam
    kasus itu, endpoint pemanggil akan menerima error yang jelas alih-alih
    ``AttributeError`` yang membingungkan.
    """
    manager = request.app.state.audio_device_manager
    if manager is None:
        raise PlaybackDeviceError(
            "Sistem audio (PortAudio/driver) tidak tersedia di server ini. "
            "Endpoint Playback tidak bisa dipakai hingga driver audio terdeteksi."
        )
    return manager


AudioDeviceManagerDep = Annotated[AudioDeviceManager, Depends(get_audio_device_manager)]


def get_playback_manager(request: Request) -> PlaybackManager:
    """Mengambil instance PlaybackManager tunggal (dibuat saat app startup).

    Harus berupa singleton (bukan dibuat baru per-request) karena
    menyimpan state playback yang sedang berjalan (stream aktif, posisi,
    device terpilih) yang harus konsisten di seluruh request.
    """
    manager = request.app.state.playback_manager
    if manager is None:
        raise PlaybackDeviceError(
            "Sistem audio (PortAudio/driver) tidak tersedia di server ini. "
            "Endpoint Playback tidak bisa dipakai hingga driver audio terdeteksi."
        )
    return manager


PlaybackManagerDep = Annotated[PlaybackManager, Depends(get_playback_manager)]


def get_zone_manager(request: Request) -> ZoneManager:
    """Mengambil instance ZoneManager tunggal (Phase 6, dibuat saat app startup).

    Sama seperti ``QueueManager``, disimpan di ``app.state`` (bukan lewat
    ``lru_cache``) karena menyimpan registry zone yang mutable dan harus
    identik dengan yang dikonsumsi oleh seluruh router (bukan dibuat ulang
    per request).
    """
    return request.app.state.zone_manager


ZoneManagerDep = Annotated[ZoneManager, Depends(get_zone_manager)]
