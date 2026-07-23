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
from announcement_server.queueing.manager import QueueManager

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
