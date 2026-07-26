"""Dependency Injection providers.

Semua dependency yang dipakai lintas router didefinisikan di sini agar
mudah di-override saat testing (``app.dependency_overrides[...] = ...``)
dan agar router tidak melakukan instansiasi objek secara langsung
(sesuai prinsip Dependency Inversion).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.core.config import AppSettings, get_settings
from announcement_server.core.exceptions import PlaybackDeviceError
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.playback.manager import PlaybackManager
from announcement_server.queueing.manager import QueueManager
from announcement_server.scheduler.manager import SchedulerManager
from announcement_server.tts.service import TTSService
from announcement_server.websocket.manager import ConnectionManager
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


def get_scheduler_manager(request: Request) -> SchedulerManager:
    """Mengambil instance SchedulerManager tunggal (Phase 8, dibuat saat app startup).

    Pola identik dengan ``get_zone_manager`` di atas — disimpan di
    ``app.state`` (bukan lewat ``lru_cache``) karena menyimpan registry
    jadwal yang mutable dan harus identik dengan yang dikonsumsi oleh
    background loop scheduler maupun seluruh router.
    """
    return request.app.state.scheduler_manager


SchedulerManagerDep = Annotated[SchedulerManager, Depends(get_scheduler_manager)]


def get_tts_service(request: Request) -> TTSService:
    """Mengambil instance TTSService tunggal (Phase 3, dibuat saat app startup).

    Dipakai Dashboard API (Phase 10) untuk melaporkan statistik cache TTS
    lewat ``GET /status``/``GET /metrics`` — TTSService sendiri tidak
    pernah diekspos langsung sebagai endpoint sintesis (itu tetap lewat
    Queue System, Phase 2/3).
    """
    return request.app.state.tts_service


TTSServiceDep = Annotated[TTSService, Depends(get_tts_service)]


def get_asset_resolver(request: Request) -> AudioAssetResolver:
    """Mengambil instance AudioAssetResolver tunggal (Phase 7, dibuat saat app startup).

    Dipakai Dashboard API (Phase 10) untuk melaporkan statistik cache
    hasil konversi ffmpeg lewat ``GET /status``/``GET /metrics``.
    """
    return request.app.state.asset_resolver


AssetResolverDep = Annotated[AudioAssetResolver, Depends(get_asset_resolver)]


def get_connection_manager(request: Request) -> ConnectionManager:
    """Mengambil instance ConnectionManager tunggal (Phase 9, dibuat saat app startup).

    Dipakai Dashboard API (Phase 10) untuk melaporkan jumlah client
    WebSocket yang sedang terhubung lewat ``GET /status``/``GET /metrics``.
    """
    return request.app.state.connection_manager


ConnectionManagerDep = Annotated[ConnectionManager, Depends(get_connection_manager)]


def get_app_started_at(request: Request) -> datetime:
    """Waktu (UTC) server selesai startup (Phase 10) — dipakai menghitung ``uptime_seconds``."""
    return request.app.state.started_at


AppStartedAtDep = Annotated[datetime, Depends(get_app_started_at)]
