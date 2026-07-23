"""Router: Health Check.

Endpoint ini WAJIB tetap ringan dan cepat (tanpa I/O berat) karena akan
dipakai oleh Windows Service watchdog / load balancer untuk menentukan
apakah proses perlu di-restart.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from announcement_server import __version__
from announcement_server.api.deps import SettingsDep
from announcement_server.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Cek status kesehatan server",
    description="Mengembalikan status server saat ini. Dipakai untuk monitoring & Windows Service watchdog.",
)
async def health_check(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app.name,
        version=__version__,
        environment=settings.app.environment,
    )
