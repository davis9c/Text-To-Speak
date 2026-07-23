"""Schema untuk endpoint /health."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Response body untuk GET /health.

    Dibuat generik (bukan hanya ``status: ok``) karena di fase-fase
    berikutnya (Phase 10 - Dashboard API, Phase 11 - Monitoring) endpoint
    ini kemungkinan akan dipakai juga oleh load balancer / monitoring
    tool untuk mengecek kesiapan sub-komponen (queue, worker, dsb).
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "app_name": "Announcement Server",
                "version": "0.1.0",
                "environment": "development",
            }
        }
    )

    status: str = Field(default="ok", description="Status kesehatan aplikasi")
    app_name: str = Field(description="Nama aplikasi")
    version: str = Field(description="Versi aplikasi (semver)")
    environment: str = Field(description="Environment saat ini")
