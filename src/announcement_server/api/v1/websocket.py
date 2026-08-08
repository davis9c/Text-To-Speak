"""Router: WebSocket Status (Phase 9).

Endpoint ``/ws/status`` — TANPA POLLING (sesuai ROADMAP.md): client
terhubung sekali, lalu menerima snapshot status awal diikuti seluruh
event (Queue Changed, Speaking, Idle, Pause, Resume, Finished) secara
push real-time dari ``ConnectionManager`` (``websocket/manager.py``).

Reuse ``_build_zone_response`` (``api/v1/zones.py``, Phase 6) untuk
snapshot awal — komputasi status per-zone (worker_running, playback_state,
pending/processing count) SUDAH benar di sana, tidak diduplikasi di sini.

``get_zone_manager_ws``/``get_connection_manager_ws`` SENGAJA didefinisikan
terpisah dari ``get_zone_manager``/(belum ada)``get_connection_manager``
di ``api/deps.py`` — dependency untuk route WebSocket menerima objek
``WebSocket`` (bukan ``Request``), sehingga butuh fungsi provider dengan
tipe parameter berbeda meski isinya (baca ``app.state``) identik. Memakai
``Depends()`` (bukan akses langsung ``websocket.app.state``) supaya
endpoint ini bisa di-override lewat ``app.dependency_overrides`` di test,
konsisten dengan seluruh router lain (``zones.py``, ``scheduler.py``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from anyio import CancelScope
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from announcement_server.api.v1.zones import _build_zone_response
from announcement_server.websocket.manager import ConnectionManager
from announcement_server.zones.manager import ZoneManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


def get_zone_manager_ws(websocket: WebSocket) -> ZoneManager:
    return websocket.app.state.zone_manager


def get_connection_manager_ws(websocket: WebSocket) -> ConnectionManager:
    return websocket.app.state.connection_manager


ZoneManagerWsDep = Annotated[ZoneManager, Depends(get_zone_manager_ws)]
ConnectionManagerWsDep = Annotated[ConnectionManager, Depends(get_connection_manager_ws)]


@router.websocket("/ws/status")
async def websocket_status(
    websocket: WebSocket, zone_manager: ZoneManagerWsDep, connection_manager: ConnectionManagerWsDep
) -> None:
    await connection_manager.connect(websocket)
    try:
        zones = zone_manager.list_zones()
        snapshot = [await _build_zone_response(zone_manager, zone.name) for zone in zones]
        await websocket.send_json(
            {
                "event": "snapshot",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {"zones": [zone.model_dump(mode="json") for zone in snapshot]},
            }
        )

        # Server murni PUSH (sesuai ROADMAP.md "Tanpa polling") — tidak ada perintah
        # apa pun yang diharapkan dari client. `receive_text()` di sini HANYA dipakai
        # untuk mendeteksi kapan client memutus koneksi (WebSocketDisconnect); isi
        # pesan yang diterima (mis. ping klien) diabaikan sepenuhnya.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - satu koneksi bermasalah tidak boleh membuat cleanup gagal atau lolos tanpa
        # tercatat; menyamakan pola defensive-logging dengan QueueWorker._run()/SchedulerManager._run()
        # (RC1-4: sebelumnya hanya WebSocketDisconnect yang ditangani eksplisit di sini, error lain
        # bergantung diam-diam pada penanganan default Starlette tanpa log yang konsisten dengan project ini).
        logger.exception("Unexpected error pada koneksi WebSocket /ws/status; koneksi akan ditutup.")
        # RC1-4: setelah error tak terduga, koneksi HARUS ditutup eksplisit (bukan hanya dicatat lalu
        # membiarkan handler selesai) -- kalau tidak, client (mis. UI TOA) hang selamanya menunggu
        # snapshot/event yang tidak akan pernah dikirim (diverifikasi di
        # test_unexpected_error_during_session_is_handled_and_cleans_up).
        try:
            await websocket.close(code=1011)
        except Exception:  # noqa: BLE001 - koneksi sudah mati bersamaan dengan error; tutup gagal tidak perlu ditangani
            logger.debug("Koneksi sudah tidak aktif saat mencoba menutup setelah error.", exc_info=True)
    finally:
        # RC1-4: cleanup registry WAJIB selalu berjalan, bahkan saat task ini
        # di-cancel (mis. TestClient menutup koneksi lewat cancel scope, atau
        # shutdown server) -- tanpa shield, await di dalam `disconnect()` bisa
        # ikut ter-cancel sehingga koneksi tertinggal di registry selamanya
        # (kebocoran connection_count, diverifikasi di
        # test_disconnect_cleans_up_connection_registry).
        with CancelScope(shield=True):
            await connection_manager.disconnect(websocket)
