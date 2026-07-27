"""Retry dengan exponential backoff (Phase 14 — Production Hardening).

Dipakai untuk kegagalan TRANSIEN (proses eksternal Piper/ffmpeg gagal
sesaat, mis. resource sistem sedang sibuk) — BUKAN untuk kegagalan
permanen (binary tidak ada, file tidak ditemukan, voice tidak dikenal),
yang percuma diulang. Pemanggil menentukan sendiri exception mana yang
layak di-retry lewat parameter ``retry_on``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


async def retry_with_backoff(
    func: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    backoff_seconds: float,
    retry_on: tuple[type[Exception], ...],
    operation_name: str = "operation",
) -> T:
    """Menjalankan ``func()`` dengan retry exponential backoff.

    Percobaan total = ``max_retries + 1``. Delay antar percobaan:
    ``backoff_seconds * (2 ** attempt)`` (0, 1, 2, ...). ``max_retries=0``
    berarti tidak ada retry sama sekali (perilaku identik tanpa fitur ini).
    """
    attempt = 0
    while True:
        try:
            return await func()
        except retry_on as exc:
            if attempt >= max_retries:
                logger.warning("%s gagal setelah %d percobaan, menyerah: %s", operation_name, attempt + 1, exc)
                raise
            delay = backoff_seconds * (2**attempt)
            logger.warning(
                "%s gagal (percobaan %d/%d): %s. Mencoba lagi dalam %.1fs...",
                operation_name,
                attempt + 1,
                max_retries + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            attempt += 1
