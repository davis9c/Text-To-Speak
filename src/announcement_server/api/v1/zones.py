"""Router: Multi Zone (Phase 6).

Endpoint di sini hanya menerjemahkan request HTTP menjadi pemanggilan ke
``ZoneManager`` (business logic ada di ``zones/manager.py``) — pola yang
sama seperti router Phase 2/4. Endpoint yang menyentuh Queue/Playback milik
satu zone memakai ulang schema DAN endpoint-logic yang sudah ada
(``QueueItemResponse``, ``QueueListResponse``, ``SelectDeviceRequest``,
``PlaybackStatusResponse``, ``SpeakRequest``) — bukan duplikat.

--------------------------------------------------------------------------
Catatan — ``POST /zones/{name}/speak`` (di luar 6 endpoint yang tertulis
literal pada ROADMAP.md Phase 6):

Roadmap Phase 6 mendaftarkan endpoint manajemen zone (GET/POST /zones,
PUT/DELETE /zones/{name}, GET /zones/{name}/queue, POST /zones/{name}/device)
tetapi belum menyediakan endpoint untuk benar-benar MENGIRIM pengumuman ke
zone tertentu. Tanpa endpoint ini, zone yang dibuat tidak punya cara
menerima pengumuman apa pun — bertentangan dengan Output Phase 6 sendiri:
"Satu server mendukung banyak jalur audio". Endpoint ini ditambahkan secara
MINIMAL (memakai ulang ``SpeakRequest``/``QueueItemResponse`` dari Phase 2
apa adanya, tanpa mengubah satu baris pun di ``schemas/queue.py`` atau
``api/v1/queue.py``) supaya setiap zone benar-benar dapat diuji end-to-end.
Endpoint global ``POST /speak`` (Phase 2) TETAP TIDAK BERUBAH dan tetap
hanya beroperasi pada zone "main", menjaga backward compatibility penuh.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status

from announcement_server.api.deps import SettingsDep, ZoneManagerDep
from announcement_server.core.exceptions import ZoneDisabledError
from announcement_server.queueing.models import DEFAULT_ACTIVE_STATUSES, QueueItemStatus
from announcement_server.schemas.playback import PlaybackStatusResponse, SelectDeviceRequest
from announcement_server.schemas.queue import QueueItemResponse, QueueListResponse, SpeakRequest
from announcement_server.schemas.zones import (
    ZoneCreateRequest,
    ZoneDeleteResponse,
    ZoneListResponse,
    ZoneResponse,
    ZoneUpdateRequest,
)
from announcement_server.zones.manager import ZoneManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/zones", tags=["Zones"])


async def _build_zone_response(zone_manager: ZoneManager, name: str) -> ZoneResponse:
    """Menggabungkan metadata Zone + status runtime (worker/playback/queue count)."""
    zone = zone_manager.get_zone(name)
    queue_manager = zone_manager.get_queue_manager(name)
    pending = await queue_manager.list_items(statuses={QueueItemStatus.PENDING})
    processing = await queue_manager.list_items(statuses={QueueItemStatus.PROCESSING})
    return ZoneResponse.build(
        zone,
        worker_running=zone_manager.is_worker_running(name),
        playback_state=zone_manager.get_playback_state(name),
        pending_count=len(pending),
        processing_count=len(processing),
    )


@router.get(
    "",
    response_model=ZoneListResponse,
    summary="Melihat daftar seluruh zone",
    description="Menampilkan seluruh zone (termasuk 'main') beserta status runtime masing-masing.",
)
async def list_zones(zone_manager: ZoneManagerDep) -> ZoneListResponse:
    zones = zone_manager.list_zones()
    responses = [await _build_zone_response(zone_manager, zone.name) for zone in zones]
    return ZoneListResponse(zones=responses, count=len(responses))


@router.post(
    "",
    response_model=ZoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Membuat zone baru",
    description=(
        "Membuat zone baru lengkap dengan Queue, Worker, dan Playback miliknya sendiri "
        "(jalur audio independen). Mengembalikan 409 jika nama zone sudah dipakai."
    ),
)
async def create_zone(payload: ZoneCreateRequest, zone_manager: ZoneManagerDep) -> ZoneResponse:
    await zone_manager.create_zone(
        payload.name,
        device_id=payload.device_id,
        volume=payload.volume,
        enabled=payload.enabled,
        max_size=payload.max_size,
        max_history=payload.max_history,
        post_playback_delay_seconds=payload.post_playback_delay_seconds,
    )
    return await _build_zone_response(zone_manager, payload.name)


@router.put(
    "/{name}",
    response_model=ZoneResponse,
    summary="Memperbarui zone (device/volume/enabled)",
    description="Pembaruan parsial — hanya field yang dikirim pada body yang diubah. Mengembalikan 404 jika zone tidak ditemukan.",
)
async def update_zone(name: str, payload: ZoneUpdateRequest, zone_manager: ZoneManagerDep) -> ZoneResponse:
    update_kwargs = payload.model_dump(exclude_unset=True)
    await zone_manager.update_zone(name, **update_kwargs)
    return await _build_zone_response(zone_manager, name)


@router.delete(
    "/{name}",
    response_model=ZoneDeleteResponse,
    summary="Menghapus zone",
    description=(
        "Menghentikan worker & playback zone secara graceful lalu menghapusnya. Zone 'main' dilindungi "
        "dan akan mengembalikan 409 jika dicoba dihapus."
    ),
)
async def delete_zone(name: str, zone_manager: ZoneManagerDep) -> ZoneDeleteResponse:
    await zone_manager.delete_zone(name)
    return ZoneDeleteResponse(name=name, deleted=True)


@router.get(
    "/{name}/queue",
    response_model=QueueListResponse,
    summary="Melihat isi antrean satu zone",
    description=(
        "Sama seperti GET /queue (Phase 2), namun khusus untuk antrean milik satu zone. Secara default "
        "hanya menampilkan item aktif (pending/processing); gunakan parameter `status` untuk memfilter."
    ),
)
async def get_zone_queue(
    name: str,
    zone_manager: ZoneManagerDep,
    status_filter: QueueItemStatus | None = Query(default=None, alias="status", description="Filter berdasarkan status tertentu"),
) -> QueueListResponse:
    queue_manager = zone_manager.get_queue_manager(name)
    statuses = {status_filter} if status_filter is not None else DEFAULT_ACTIVE_STATUSES
    items = await queue_manager.list_items(statuses=statuses)

    pending_items = (
        items
        if statuses == {QueueItemStatus.PENDING}
        else await queue_manager.list_items(statuses={QueueItemStatus.PENDING})
    )

    responses = [
        QueueItemResponse.from_item(
            item,
            position=queue_manager.position_of(item.id, pending_items) if item.status == QueueItemStatus.PENDING else None,
        )
        for item in items
    ]
    return QueueListResponse(items=responses, count=len(responses))


@router.post(
    "/{name}/device",
    response_model=PlaybackStatusResponse,
    summary="Memilih output device aktif untuk satu zone",
    description="Sama seperti POST /device (Phase 4), namun khusus untuk output device milik satu zone.",
)
async def select_zone_device(name: str, payload: SelectDeviceRequest, zone_manager: ZoneManagerDep) -> PlaybackStatusResponse:
    await zone_manager.update_zone(name, device_id=payload.device_id)
    playback_manager = zone_manager.get_playback_manager(name)
    if playback_manager is None:
        return PlaybackStatusResponse(state="idle", current_file=None, selected_device_id=payload.device_id)
    return PlaybackStatusResponse(
        state=playback_manager.state,
        current_file=playback_manager.current_file,
        selected_device_id=playback_manager.selected_device_id,
    )


@router.post(
    "/{name}/speak",
    response_model=QueueItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Menambahkan pengumuman baru ke antrean satu zone",
    description=(
        "Sama seperti POST /speak (Phase 2), namun mengarahkan pengumuman ke antrean & jalur audio milik "
        "zone tertentu alih-alih zone 'main'. Mengembalikan 409 jika zone sedang nonaktif (enabled=false)."
    ),
)
async def speak_to_zone(name: str, payload: SpeakRequest, zone_manager: ZoneManagerDep, settings: SettingsDep) -> QueueItemResponse:
    zone = zone_manager.get_zone(name)
    if not zone.enabled:
        raise ZoneDisabledError(
            f"Zone '{name}' sedang nonaktif dan tidak dapat menerima pengumuman baru.",
            details={"name": name},
        )

    queue_manager = zone_manager.get_queue_manager(name)
    voice = payload.voice or settings.tts.default_voice
    item = await queue_manager.enqueue(
        text=payload.text,
        priority=payload.priority,
        voice=voice,
        speed=payload.speed,
        pitch=payload.pitch,
        volume=payload.volume,
    )
    pending_items = await queue_manager.list_items(statuses={QueueItemStatus.PENDING})
    position = queue_manager.position_of(item.id, pending_items)
    return QueueItemResponse.from_item(item, position=position)
