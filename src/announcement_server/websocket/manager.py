"""Connection Manager (Phase 9 — WebSocket).

Melacak client WebSocket yang terhubung ke ``/ws/status`` dan mem-broadcast
event ke SELURUH client sekaligus. Kelas ini murni infrastruktur pengiriman
pesan — memenuhi kontrak ``EventPublisher`` (``core/events.py``) sehingga
bisa langsung disuntikkan sebagai ``on_event`` ke ``QueueManager``/
``PlaybackManager`` tanpa kelas manapun perlu tahu detail WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Registry client WebSocket + broadcast pesan JSON ke seluruhnya."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Menerima (accept) koneksi baru dan mendaftarkannya ke registry."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("Client WebSocket terhubung (total=%d).", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Menghapus koneksi dari registry. Aman dipanggil walau koneksi sudah tidak terdaftar."""
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("Client WebSocket terputus (total=%d).", len(self._connections))

    async def broadcast(self, event_type: str, data: dict) -> None:
        """Mengirim satu event ke SELURUH client yang terhubung — memenuhi kontrak ``EventPublisher``.

        Client yang koneksinya ternyata sudah putus (belum sempat
        ``disconnect()``, mis. koneksi terputus mendadak tanpa close
        frame) dilewati secara graceful dan dibersihkan dari registry —
        satu client bermasalah tidak boleh mengganggu broadcast ke client
        lain, apalagi mengganggu Queue/Playback yang mengirim event ini.
        """
        async with self._lock:
            targets = list(self._connections)
        if not targets:
            return

        message = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 - satu client bermasalah tidak boleh menggagalkan broadcast lain
                stale.append(websocket)

        if stale:
            async with self._lock:
                for websocket in stale:
                    self._connections.discard(websocket)
            logger.info("Membersihkan %d koneksi WebSocket yang sudah tidak aktif.", len(stale))
