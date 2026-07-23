"""Queue Worker.

Worker pada Phase 2 HANYA bertanggung jawab mengonsumsi antrean dan
mengelola transisi status (PENDING -> PROCESSING -> COMPLETED/FAILED).
Belum ada TTS maupun audio playback di sini — itu adalah scope Phase 3
(TTS Engine), Phase 4 (Audio Playback), dan disatukan penuh sebagai
pipeline di Phase 5 (Worker pipeline: Queue -> Cache -> Generate ->
Playback -> Delay -> Queue Berikutnya).

Agar Phase 5 nanti tidak perlu menulis ulang ``QueueWorker``, proses
aktual per-item didelegasikan ke sebuah callback ``item_processor`` yang
di-inject lewat constructor (Dependency Injection + Open/Closed
Principle). Phase 5 tinggal menyuntikkan processor baru (pipeline
TTS+Playback) tanpa mengubah kelas ini sama sekali.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueueItem

logger = logging.getLogger(__name__)

ItemProcessor = Callable[[QueueItem], Awaitable[None]]


async def default_stub_processor(item: QueueItem) -> None:
    """Processor default untuk Phase 2.

    Belum melakukan TTS/playback apa pun — hanya mencatat log bahwa item
    "diproses". Digantikan oleh pipeline TTS + Playback pada Phase 5.
    """
    logger.info("Memproses item (stub, TTS belum tersedia): id=%s text=%r", item.id, item.text)


class QueueWorker:
    """Background task tunggal yang mengonsumsi ``QueueManager`` secara terus-menerus."""

    def __init__(self, manager: QueueManager, item_processor: ItemProcessor = default_stub_processor) -> None:
        self._manager = manager
        self._item_processor = item_processor
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def start(self) -> None:
        """Memulai worker sebagai asyncio background task. Idempotent."""
        if self._task is not None:
            logger.warning("QueueWorker sudah berjalan, pemanggilan start() diabaikan.")
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="queue-worker")
        logger.info("QueueWorker dimulai.")

    async def stop(self) -> None:
        """Menghentikan worker secara graceful. Dipanggil saat aplikasi shutdown."""
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("QueueWorker dihentikan.")

    async def _run(self) -> None:
        while self._running:
            try:
                item = await self._manager.dequeue_for_processing()
                if item is None:
                    # Item sudah dibatalkan sebelum sempat diproses, lanjut.
                    continue
                await self._process_item(item)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - jaring pengaman: loop worker TIDAK BOLEH mati
                logger.exception("Unexpected error pada QueueWorker loop; melanjutkan setelah jeda singkat.")
                await asyncio.sleep(1)

    async def _process_item(self, item: QueueItem) -> None:
        try:
            await self._item_processor(item)
        except Exception as exc:  # noqa: BLE001 - error per-item tidak boleh mematikan worker
            logger.exception("Gagal memproses item id=%s: %s", item.id, exc)
            await self._manager.mark_failed(item.id, str(exc))
            return
        await self._manager.mark_completed(item.id)
