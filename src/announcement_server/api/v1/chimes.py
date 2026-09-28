"""Router: Chime Discovery.

Mengekspos `ChimeCatalog` (daftar file audio chime di ``announcement.chime_dir``)
sebagai REST API publik read-only. Tujuannya memberi client (mis. dashboard
web) daftar chime yang tersedia untuk menampilkan dropdown pemilihan chime —
nilai ``file`` pada tiap chime bisa langsung dipakai di field ``chime`` pada
``POST /speak``, ``POST /zones/{name}/speak``, maupun jadwal scheduler.

Router ini SENGAJA tidak pernah menyentuh filesystem secara langsung:
seluruh data berasal dari ``ChimeCatalog``, dan directory scan dilakukan
per-request sehingga chime yang ditambahkan user langsung muncul di sini
tanpa restart server.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from announcement_server.api.deps import ChimeCatalogDep
from announcement_server.schemas.chime import ChimeInfo, ChimeListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chimes", tags=["Chime Discovery"])


@router.get(
    "",
    response_model=ChimeListResponse,
    summary="Daftar chime yang tersedia",
    description="Mengembalikan seluruh file audio chime di announcement.chime_dir (folder khusus chime). "
    "Direktori kosong/tidak ada menghasilkan `chimes: []`, bukan error. `default_chime` berisi `file` "
    "dari chime bertanda default (`chime.*`/`default.*`), atau null jika tidak ada.",
)
async def list_chimes(chime_catalog: ChimeCatalogDep) -> ChimeListResponse:
    """Menampilkan seluruh chime yang tersedia beserta chime default.

    Direktori kosong/tidak ada menghasilkan ``chimes: []``; ``default_chime``
    bernilai null jika tidak ada chime bertanda default.
    """
    profiles = await chime_catalog.list()
    default_profile = await chime_catalog.get_default()
    return ChimeListResponse(
        chimes=[ChimeInfo.from_profile(profile) for profile in profiles],
        count=len(profiles),
        default_chime=default_profile.file if default_profile else None,
    )
