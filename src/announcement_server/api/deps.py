"""Dependency Injection providers.

Semua dependency yang dipakai lintas router didefinisikan di sini agar
mudah di-override saat testing (``app.dependency_overrides[...] = ...``)
dan agar router tidak melakukan instansiasi objek secara langsung
(sesuai prinsip Dependency Inversion).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from announcement_server.core.config import AppSettings, get_settings

# Alias tipe untuk dipakai di signature endpoint, mis:
#   async def health(settings: SettingsDep): ...
SettingsDep = Annotated[AppSettings, Depends(get_settings)]
