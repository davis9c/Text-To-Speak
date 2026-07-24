"""Model domain untuk Multi Zone (Phase 6).

``Zone`` SENGAJA hanya berisi metadata murni (nama, status enable, device,
volume, timestamp) — bukan objek runtime seperti ``QueueManager`` atau
``PlaybackManager``. Ini konsisten dengan pola yang sudah dipakai domain
lain di project ini (mis. ``QueueItem`` di ``queueing/models.py`` juga
murni data, sedangkan orkestrasi ada di ``QueueManager``). Pemisahan ini
membuat ``Zone`` aman diserialisasi langsung sebagai response API
(``schemas/zones.py``) tanpa mengekspos komponen internal.

Objek runtime tiap zone (Queue/Worker/Playback/Pipeline) dikelola secara
privat oleh ``ZoneManager`` (lihat ``zones/manager.py``).
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Nama zone dipakai langsung sebagai path segment URL (`/zones/{name}/...`)
# dan sebagai nama subfolder (`cache/zone_audio/{name}/`) di beberapa
# kandidat implementasi penyimpanan berikutnya — maka dibatasi ke karakter
# yang aman untuk keduanya.
ZONE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")

# Nama zone yang selalu ada sejak startup dan dilindungi dari penghapusan
# (lihat ZoneProtectedError) karena dipakai oleh seluruh endpoint Phase 1-5
# (/speak, /queue, /clear, /devices, /device, /pause, /resume, /stop) demi
# backward compatibility penuh.
MAIN_ZONE_NAME = "main"


class Zone(BaseModel):
    """Representasi metadata satu Zone (jalur audio independen)."""

    model_config = ConfigDict(validate_assignment=True)

    name: str = Field(description="Nama unik zone, dipakai sebagai path segment (/zones/{name}/...)")
    enabled: bool = Field(description="Jika false, worker zone ini tidak memproses antrean")
    device_id: int | None = Field(default=None, description="ID output device untuk zone ini (lihat GET /devices)")
    volume: float = Field(default=1.0, description="Volume/gain khusus zone ini (0.0 - 2.0)")
    created_at: datetime = Field(description="Waktu zone dibuat (UTC)")
    updated_at: datetime = Field(description="Waktu terakhir metadata zone berubah (UTC)")
