"""Schema untuk Maintenance API (Phase 14 — Production Hardening)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CacheCleanupRequest(BaseModel):
    """Request body untuk POST /maintenance/cache/cleanup. Seluruh field opsional."""

    tts_max_age_days: float | None = Field(
        default=None, ge=0, description="Override tts.cache_max_age_days untuk pemanggilan ini saja."
    )
    announcement_max_age_days: float | None = Field(
        default=None, ge=0, description="Override announcement.cache_max_age_days untuk pemanggilan ini saja."
    )


class CacheCleanupStats(BaseModel):
    deleted_count: int = Field(description="Jumlah file yang dihapus")
    freed_bytes: int = Field(description="Total ukuran file yang dihapus (bytes)")


class CacheCleanupResponse(BaseModel):
    """Response body untuk POST /maintenance/cache/cleanup."""

    tts_cache: CacheCleanupStats
    announcement_cache: CacheCleanupStats
