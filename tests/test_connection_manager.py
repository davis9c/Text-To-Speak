"""Unit test untuk ConnectionManager (Phase 9).

Memakai double sederhana untuk ``WebSocket`` (bukan koneksi sungguhan)
supaya broadcast/stale-cleanup bisa diuji tanpa server HTTP sungguhan —
test end-to-end lewat koneksi WebSocket asli ada di
``test_websocket_status_api.py``.
"""

from __future__ import annotations

import pytest

from announcement_server.websocket.manager import ConnectionManager


class FakeWebSocket:
    """Double minimal untuk ``fastapi.WebSocket`` — hanya method yang dipakai ConnectionManager."""

    def __init__(self, *, fail_on_send: bool = False) -> None:
        self.accepted = False
        self.sent_messages: list[dict] = []
        self._fail_on_send = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        if self._fail_on_send:
            raise RuntimeError("Koneksi sudah putus (simulasi).")
        self.sent_messages.append(message)


@pytest.fixture()
def manager() -> ConnectionManager:
    return ConnectionManager()


async def test_connect_accepts_and_registers(manager: ConnectionManager) -> None:
    ws = FakeWebSocket()
    await manager.connect(ws)
    assert ws.accepted is True
    assert manager.connection_count == 1


async def test_disconnect_removes_from_registry(manager: ConnectionManager) -> None:
    ws = FakeWebSocket()
    await manager.connect(ws)
    await manager.disconnect(ws)
    assert manager.connection_count == 0


async def test_disconnect_unknown_connection_is_safe(manager: ConnectionManager) -> None:
    ws = FakeWebSocket()
    await manager.disconnect(ws)  # tidak pernah connect() - tidak boleh melempar
    assert manager.connection_count == 0


async def test_broadcast_sends_to_all_connected_clients(manager: ConnectionManager) -> None:
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect(ws1)
    await manager.connect(ws2)

    await manager.broadcast("queue_changed", {"reason": "enqueued"})

    assert len(ws1.sent_messages) == 1
    assert len(ws2.sent_messages) == 1
    assert ws1.sent_messages[0]["event"] == "queue_changed"
    assert ws1.sent_messages[0]["data"] == {"reason": "enqueued"}
    assert "timestamp" in ws1.sent_messages[0]


async def test_broadcast_with_no_connections_is_safe(manager: ConnectionManager) -> None:
    await manager.broadcast("queue_changed", {"reason": "enqueued"})  # tidak boleh melempar


async def test_broadcast_skips_and_cleans_up_stale_connection(manager: ConnectionManager) -> None:
    healthy = FakeWebSocket()
    stale = FakeWebSocket(fail_on_send=True)
    await manager.connect(healthy)
    await manager.connect(stale)

    await manager.broadcast("idle", {})

    assert len(healthy.sent_messages) == 1  # client sehat tetap menerima
    assert manager.connection_count == 1  # client stale otomatis dibersihkan
