"""Router: Queue System (Phase 2).

Endpoint di sini hanya bertanggung jawab menerima request HTTP dan
menerjemahkannya menjadi pemanggilan ke ``QueueManager`` (business logic).
Tidak ada logika antrean yang ditulis langsung di layer router — ini
menjaga pemisahan tanggung jawab (Single Responsibility) dan membuat
``QueueManager`` bisa dites tanpa perlu HTTP client sama sekali.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Query, status

from announcement_server.api.deps import QueueManagerDep
from announcement_server.queueing.models import QueueItemStatus
from announcement_server.schemas.queue import (
    ClearResponse,
    QueueItemResponse,
    QueueListResponse,
    SpeakRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Queue"])

# Status default yang ditampilkan GET /queue jika parameter `status` tidak
# diberikan: hanya item yang masih "aktif" (belum final). Riwayat lengkap
# (termasuk completed/failed/cancelled) tetap bisa diakses lewat parameter
# `status` eksplisit — endpoint riwayat penuh (`GET /history`) baru
# direncanakan pada Phase 10 sesuai roadmap.
_DEFAULT_ACTIVE_STATUSES = {QueueItemStatus.PENDING, QueueItemStatus.PROCESSING}


@router.post(
    "/speak",
    response_model=QueueItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Menambahkan pengumuman baru ke antrean",
    description=(
        "Menambahkan teks pengumuman ke antrean untuk diproses. "
        "Pada Phase 2, item hanya sampai berstatus completed sebagai placeholder "
        "(TTS/audio nyata baru tersedia mulai Phase 3)."
    ),
)
async def speak(payload: SpeakRequest, manager: QueueManagerDep) -> QueueItemResponse:
    item = await manager.enqueue(text=payload.text, priority=payload.priority)
    pending_items = await manager.list_items(statuses={QueueItemStatus.PENDING})
    position = manager.position_of(item.id, pending_items)
    return QueueItemResponse.from_item(item, position=position)


@router.get(
    "/queue",
    response_model=QueueListResponse,
    summary="Melihat isi antrean",
    description=(
        "Secara default hanya menampilkan item yang masih aktif (pending/processing). "
        "Gunakan parameter `status` untuk melihat status tertentu, termasuk riwayat "
        "(completed/failed/cancelled) selama masih tersimpan di memory."
    ),
)
async def get_queue(
    manager: QueueManagerDep,
    status_filter: QueueItemStatus | None = Query(default=None, alias="status", description="Filter berdasarkan status tertentu"),
) -> QueueListResponse:
    statuses = {status_filter} if status_filter is not None else _DEFAULT_ACTIVE_STATUSES
    items = await manager.list_items(statuses=statuses)

    pending_items = (
        items if statuses == {QueueItemStatus.PENDING} else await manager.list_items(statuses={QueueItemStatus.PENDING})
    )

    responses = [
        QueueItemResponse.from_item(
            item,
            position=manager.position_of(item.id, pending_items) if item.status == QueueItemStatus.PENDING else None,
        )
        for item in items
    ]
    return QueueListResponse(items=responses, count=len(responses))


@router.delete(
    "/queue/{item_id}",
    response_model=QueueItemResponse,
    summary="Membatalkan satu item pada antrean",
    description="Hanya item berstatus PENDING yang dapat dibatalkan. Mengembalikan 404 jika id tidak ditemukan.",
)
async def delete_queue_item(item_id: uuid.UUID, manager: QueueManagerDep) -> QueueItemResponse:
    item = await manager.cancel_item(item_id)
    return QueueItemResponse.from_item(item)


@router.post(
    "/clear",
    response_model=ClearResponse,
    summary="Membatalkan seluruh item PENDING pada antrean",
    description="Item yang sedang PROCESSING tidak terpengaruh dan akan tetap diselesaikan oleh worker.",
)
async def clear_queue(manager: QueueManagerDep) -> ClearResponse:
    cleared_count = await manager.clear()
    return ClearResponse(cleared_count=cleared_count)
