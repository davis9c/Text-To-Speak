"""Kontrak event domain (Phase 9 — WebSocket).

``QueueManager`` (Phase 2) dan ``PlaybackManager`` (Phase 4) memberi tahu
perubahan state lewat satu callable generik (``EventPublisher``) TANPA
tahu siapa yang mendengarkan — bisa WebSocket (``websocket/manager.py``),
log, metrics, atau apa pun di masa depan (Dependency Inversion
Principle). Modul ini SENGAJA diletakkan di ``core/`` (bukan
``websocket/``) supaya ``queueing/`` dan ``playback/`` tidak perlu
bergantung pada detail implementasi WebSocket sama sekali.

Nama event (``EVENT_*``) didefinisikan SEKALI di sini — dipakai oleh
publisher (``QueueManager``, ``PlaybackManager``) MAUPUN consumer
(``websocket/router.py``) — sesuai daftar pada ROADMAP.md Phase 9:
Queue Changed, Speaking, Idle, Pause, Resume, Finished.
"""

from __future__ import annotations

from typing import Awaitable, Callable

EventPublisher = Callable[[str, dict], Awaitable[None]]


async def noop_event_publisher(event_type: str, data: dict) -> None:
    """Default ``on_event`` saat tidak ada listener terpasang (dipakai luas oleh test unit)."""
    return None


# --- Nama event (ROADMAP.md Phase 9) ------------------------------------------

EVENT_QUEUE_CHANGED = "queue_changed"
EVENT_SPEAKING = "speaking"
EVENT_IDLE = "idle"
EVENT_PAUSE = "pause"
EVENT_RESUME = "resume"
EVENT_FINISHED = "finished"
