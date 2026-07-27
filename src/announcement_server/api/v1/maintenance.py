"""Router: Maintenance (Phase 14 — Production Hardening).

Reuse ``TTSService.cleanup_cache()``/``AudioAssetResolver.cleanup_cache()``
(Phase 3/7) — logika hapus file ada di domain masing-masing, router ini
murni menerjemahkan HTTP request ke pemanggilan itu.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from announcement_server.api.deps import AssetResolverDep, TTSServiceDep
from announcement_server.schemas.maintenance import CacheCleanupRequest, CacheCleanupResponse, CacheCleanupStats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


@router.post(
    "/cache/cleanup",
    response_model=CacheCleanupResponse,
    summary="Membersihkan cache TTS & Announcement Engine berdasarkan usia file",
    description=(
        "Menghapus file cache yang lebih tua dari batas usia yang dikonfigurasi "
        "(`tts.cache_max_age_days` / `announcement.cache_max_age_days`), atau override lewat body. "
        "Field yang null (default) berarti TIDAK ada file yang dihapus untuk cache tsb."
    ),
)
async def cleanup_cache(
    payload: CacheCleanupRequest, tts_service: TTSServiceDep, asset_resolver: AssetResolverDep
) -> CacheCleanupResponse:
    tts_deleted, tts_freed = await tts_service.cleanup_cache(max_age_days=payload.tts_max_age_days)
    announcement_deleted, announcement_freed = await asset_resolver.cleanup_cache(
        max_age_days=payload.announcement_max_age_days
    )
    logger.info(
        "Cache cleanup manual: tts=%d file (%d bytes), announcement=%d file (%d bytes)",
        tts_deleted,
        tts_freed,
        announcement_deleted,
        announcement_freed,
    )
    return CacheCleanupResponse(
        tts_cache=CacheCleanupStats(deleted_count=tts_deleted, freed_bytes=tts_freed),
        announcement_cache=CacheCleanupStats(deleted_count=announcement_deleted, freed_bytes=announcement_freed),
    )
