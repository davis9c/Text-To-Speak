"""Router: Dashboard API (Phase 10).

Endpoint di sini murni AGREGASI/READ-ONLY — tidak ada state baru yang
dikelola, semuanya dihitung langsung dari komponen yang sudah ada
(``ZoneManager`` Phase 6, ``SchedulerManager`` Phase 8, ``TTSService``
Phase 3, ``AudioAssetResolver`` Phase 7, ``ConnectionManager`` Phase 9).
Tidak ada duplikasi logika apa pun — ``_build_zone_response`` (Phase 6,
``zones.py``) dipakai ulang untuk bagian "Queue/Worker/Device/Zone/
Current Audio" pada ``GET /status``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from announcement_server import __version__
from announcement_server.api.deps import (
    AppStartedAtDep,
    AssetResolverDep,
    ConnectionManagerDep,
    SchedulerManagerDep,
    SettingsDep,
    TTSServiceDep,
    ZoneManagerDep,
)
from announcement_server.api.v1.zones import _build_zone_response
from announcement_server.queueing.models import FINISHED_STATUSES, QueueItemStatus
from announcement_server.schemas.dashboard import (
    CacheStatsResponse,
    HistoryItemResponse,
    HistoryResponse,
    MetricsResponse,
    StatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Dashboard"])


async def _build_cache_stats(directory: str, stats: tuple[int, int]) -> CacheStatsResponse:
    file_count, total_size_bytes = stats
    return CacheStatsResponse(directory=directory, file_count=file_count, total_size_bytes=total_size_bytes)


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Snapshot lengkap kondisi server saat ini",
    description=(
        "Menggabungkan status seluruh zone (Queue/Worker/Device/Current Audio — sama seperti GET /zones), "
        "statistik cache TTS & Announcement Engine, jumlah client WebSocket yang terhubung, dan uptime server."
    ),
)
async def get_status(
    zone_manager: ZoneManagerDep,
    settings: SettingsDep,
    tts_service: TTSServiceDep,
    asset_resolver: AssetResolverDep,
    connection_manager: ConnectionManagerDep,
    started_at: AppStartedAtDep,
) -> StatusResponse:
    zones = zone_manager.list_zones()
    zone_responses = [await _build_zone_response(zone_manager, zone.name) for zone in zones]

    tts_stats = await tts_service.get_cache_stats()
    announcement_stats = await asset_resolver.get_cache_stats()
    uptime_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

    return StatusResponse(
        app_name=settings.app.name,
        version=__version__,
        environment=settings.app.environment,
        uptime_seconds=uptime_seconds,
        zones=zone_responses,
        tts_cache=await _build_cache_stats(settings.tts.cache_dir, tts_stats),
        announcement_cache=await _build_cache_stats(settings.announcement.converted_cache_dir, announcement_stats),
        connected_websocket_clients=connection_manager.connection_count,
    )


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Riwayat pengumuman yang sudah selesai diproses",
    description=(
        "Menampilkan item berstatus final (completed/failed/cancelled secara default) lintas SELURUH zone, "
        "diurutkan dari yang paling baru. Gunakan `zone` untuk membatasi ke satu zone, `status` untuk status "
        "tertentu saja, dan `limit` untuk membatasi jumlah hasil."
    ),
)
async def get_history(
    zone_manager: ZoneManagerDep,
    zone: str | None = Query(default=None, description="Batasi ke satu zone tertentu. Kosongkan untuk seluruh zone."),
    status_filter: QueueItemStatus | None = Query(
        default=None, alias="status", description="Batasi ke satu status tertentu. Kosongkan untuk seluruh status final."
    ),
    limit: int = Query(default=100, ge=1, le=1000, description="Jumlah maksimum item yang dikembalikan"),
) -> HistoryResponse:
    zone_names = [zone] if zone is not None else [z.name for z in zone_manager.list_zones()]
    # Memastikan `zone` yang diminta benar-benar ada — melempar ZoneNotFoundError (404) jika tidak,
    # konsisten dengan endpoint lain yang menerima nama zone (mis. GET /zones/{name}/queue).
    if zone is not None:
        zone_manager.get_zone(zone)

    statuses = {status_filter} if status_filter is not None else FINISHED_STATUSES

    items: list[HistoryItemResponse] = []
    for zone_name in zone_names:
        queue_manager = zone_manager.get_queue_manager(zone_name)
        zone_items = await queue_manager.list_items(statuses=statuses)
        items.extend(HistoryItemResponse.from_item(item, zone=zone_name) for item in zone_items)

    items.sort(key=lambda i: i.updated_at, reverse=True)
    limited = items[:limit]
    return HistoryResponse(items=limited, count=len(limited))


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Ringkasan angka untuk monitoring/dashboard",
    description="Jumlah item per status (agregasi seluruh zone), jumlah zone, jadwal aktif, client WebSocket, cache, dan uptime.",
)
async def get_metrics(
    zone_manager: ZoneManagerDep,
    scheduler_manager: SchedulerManagerDep,
    settings: SettingsDep,
    tts_service: TTSServiceDep,
    asset_resolver: AssetResolverDep,
    connection_manager: ConnectionManagerDep,
    started_at: AppStartedAtDep,
) -> MetricsResponse:
    zones = zone_manager.list_zones()
    totals: dict[str, int] = {}
    for zone in zones:
        queue_manager = zone_manager.get_queue_manager(zone.name)
        for item in await queue_manager.list_items():
            totals[item.status.value] = totals.get(item.status.value, 0) + 1

    active_schedules = sum(1 for schedule in scheduler_manager.list_schedules() if schedule.enabled)

    tts_stats = await tts_service.get_cache_stats()
    announcement_stats = await asset_resolver.get_cache_stats()
    uptime_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

    return MetricsResponse(
        uptime_seconds=uptime_seconds,
        zones_count=len(zones),
        total_items_by_status=totals,
        active_schedules_count=active_schedules,
        connected_websocket_clients=connection_manager.connection_count,
        tts_cache=await _build_cache_stats(settings.tts.cache_dir, tts_stats),
        announcement_cache=await _build_cache_stats(settings.announcement.converted_cache_dir, announcement_stats),
    )
