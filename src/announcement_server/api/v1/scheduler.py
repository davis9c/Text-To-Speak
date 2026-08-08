"""Router: Scheduler (Phase 8).

Endpoint di sini hanya menerjemahkan request HTTP menjadi pemanggilan ke
``SchedulerManager`` (business logic ada di ``scheduler/manager.py``) —
pola yang sama seperti router Phase 6 (``zones.py``). Body
``announcement`` memakai ulang ``SpeakRequest`` (Phase 2/7) apa adanya
(lihat ``schemas/scheduler.py``); endpoint ``POST /{id}/trigger``
memakai ulang ``QueueItemResponse`` (Phase 2/7) sebagai response —
BUKAN duplikasi.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, status

from announcement_server.api.deps import SchedulerManagerDep
from announcement_server.scheduler.models import AnnouncementSpec
from announcement_server.schemas.queue import QueueItemResponse
from announcement_server.schemas.scheduler import (
    ScheduleCreateRequest,
    ScheduleDeleteResponse,
    ScheduleListResponse,
    ScheduleResponse,
    ScheduleUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


def _to_announcement_spec(payload) -> AnnouncementSpec:  # noqa: ANN001 - payload: SpeakRequest (schemas/queue.py)
    """Mengonversi ``SpeakRequest`` (schema, Phase 2/7) menjadi ``AnnouncementSpec`` (domain, Phase 8).

    Memakai ``resolved_text`` (Phase 7) supaya teks tampilan otomatis untuk
    ``type='audio'`` tanpa ``text`` eksplisit ikut konsisten dengan
    ``POST /speak``/``POST /zones/{name}/speak``.
    """
    return AnnouncementSpec(
        type=payload.type,
        text=payload.resolved_text,
        file=payload.file,
        priority=payload.priority,
        engine=payload.engine,
        voice=payload.voice,
        speed=payload.speed,
        pitch=payload.pitch,
        volume=payload.volume,
        chime=payload.chime,
    )


@router.get(
    "",
    response_model=ScheduleListResponse,
    summary="Melihat daftar seluruh jadwal",
    description="Mengembalikan seluruh jadwal yang terdaftar di server ini beserta status `enabled` dan `next_run_at` masing-masing.",
)
async def list_schedules(scheduler_manager: SchedulerManagerDep) -> ScheduleListResponse:
    schedules = scheduler_manager.list_schedules()
    responses = [ScheduleResponse.model_validate(entry) for entry in schedules]
    return ScheduleListResponse(schedules=responses, count=len(responses))


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Membuat jadwal baru",
    description=(
        "Mendaftarkan jadwal pemicu pengumuman otomatis (daily/weekly/once). Mengembalikan 422 jika "
        "konfigurasi tidak valid atau tidak akan pernah terpicu (mis. 'once' dengan tanggal yang sudah lewat)."
    ),
)
async def create_schedule(payload: ScheduleCreateRequest, scheduler_manager: SchedulerManagerDep) -> ScheduleResponse:
    entry = await scheduler_manager.create_schedule(
        name=payload.name,
        enabled=payload.enabled,
        zone=payload.zone,
        recurrence=payload.recurrence,
        time_of_day=payload.time_of_day,
        days_of_week=payload.days_of_week,
        run_date=payload.run_date,
        announcement=_to_announcement_spec(payload.announcement),
    )
    return ScheduleResponse.model_validate(entry)


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Melihat detail satu jadwal",
    description="Mengembalikan detail satu jadwal berdasarkan id. Mengembalikan 404 jika jadwal tidak ditemukan.",
)
async def get_schedule(schedule_id: uuid.UUID, scheduler_manager: SchedulerManagerDep) -> ScheduleResponse:
    entry = scheduler_manager.get_schedule(schedule_id)
    return ScheduleResponse.model_validate(entry)


@router.put(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Memperbarui jadwal",
    description="Pembaruan parsial — hanya field yang dikirim pada body yang diubah. Mengembalikan 404 jika jadwal tidak ditemukan.",
)
async def update_schedule(
    schedule_id: uuid.UUID, payload: ScheduleUpdateRequest, scheduler_manager: SchedulerManagerDep
) -> ScheduleResponse:
    update_kwargs = payload.model_dump(exclude_unset=True, exclude={"announcement"})
    if "announcement" in payload.model_fields_set and payload.announcement is not None:
        update_kwargs["announcement"] = _to_announcement_spec(payload.announcement)
    entry = await scheduler_manager.update_schedule(schedule_id, **update_kwargs)
    return ScheduleResponse.model_validate(entry)


@router.delete(
    "/{schedule_id}",
    response_model=ScheduleDeleteResponse,
    summary="Menghapus jadwal",
    description="Menghapus jadwal secara permanen (bukan disable). Mengembalikan 404 jika jadwal tidak ditemukan.",
)
async def delete_schedule(schedule_id: uuid.UUID, scheduler_manager: SchedulerManagerDep) -> ScheduleDeleteResponse:
    await scheduler_manager.delete_schedule(schedule_id)
    return ScheduleDeleteResponse(id=schedule_id, deleted=True)


@router.post(
    "/{schedule_id}/trigger",
    response_model=QueueItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Memicu satu jadwal secara manual (verifikasi/testing)",
    description=(
        "Segera meng-enqueue pengumuman jadwal ini ke zone tujuannya, TANPA memengaruhi jadwal "
        "pemicu otomatis berikutnya (`next_run_at` tidak berubah). Berguna untuk menguji isi "
        "pengumuman suatu jadwal tanpa menunggu waktu terjadwal."
    ),
)
async def trigger_schedule(schedule_id: uuid.UUID, scheduler_manager: SchedulerManagerDep) -> QueueItemResponse:
    item = await scheduler_manager.trigger_now(schedule_id)
    return QueueItemResponse.from_item(item)
