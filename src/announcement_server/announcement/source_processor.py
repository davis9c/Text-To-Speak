"""Announcement Source Processor (Phase 7 — Announcement Engine).

Item processor Stage 2 ("Cache/Generate" pada pipeline Phase 5) yang
men-dispatch ke ``TTSQueueProcessor`` (Phase 3, TIDAK diubah sama sekali)
atau ``AudioAssetResolver`` (Phase 7, lihat ``asset_resolver.py``)
berdasarkan ``item.announcement_type``.

Disuntikkan ke ``AnnouncementPipelineProcessor`` (Phase 5) SEBAGAI GANTI
``TTSQueueProcessor`` langsung — parameter itu bernama ``tts_processor``
tapi kontraknya murni ``ItemProcessor``
(``Callable[[QueueItem], Awaitable[None]]``, lihat ``queueing/worker.py``),
jadi ``AnnouncementPipelineProcessor`` (Stage 3 Playback, Stage 4 Delay)
TIDAK PERLU diubah SAMA SEKALI untuk mendukung Phase 7 — kelas ini murni
menggantikan APA yang mengisi ``item.audio_file_path`` sebelum tahap
Playback berjalan.

Kegagalan resolusi file audio (``AudioAssetNotFoundError``,
``AudioConversionUnavailableError``, ``AudioConversionError``) SENGAJA
dibiarkan menjalar ke atas — kontrak yang sama seperti kegagalan TTS
(Phase 3): ``QueueWorker`` akan menangkapnya dan menandai item FAILED
beserta pesan error-nya.
"""

from __future__ import annotations

import logging

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.core.exceptions import AudioAssetNotFoundError
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import AnnouncementType, QueueItem
from announcement_server.queueing.worker import ItemProcessor

logger = logging.getLogger(__name__)


class AnnouncementSourceProcessor:
    """Dispatcher Stage 2: TTS (Phase 3) atau Audio Asset statis (Phase 7)."""

    def __init__(
        self,
        tts_processor: ItemProcessor,
        asset_resolver: AudioAssetResolver,
        queue_manager: QueueManager,
    ) -> None:
        self._tts_processor = tts_processor
        self._asset_resolver = asset_resolver
        self._queue_manager = queue_manager

    async def __call__(self, item: QueueItem) -> None:
        """Dipanggil oleh QueueWorker (lewat AnnouncementPipelineProcessor) untuk setiap item PROCESSING."""
        if item.announcement_type == AnnouncementType.AUDIO:
            await self._process_audio(item)
        else:
            await self._tts_processor(item)

    async def _process_audio(self, item: QueueItem) -> None:
        if not item.source_file:
            raise AudioAssetNotFoundError(
                "Item bertipe 'audio' tidak memiliki `source_file` yang valid.",
                details={"item_id": str(item.id)},
            )

        audio_file_path, cache_hit = await self._asset_resolver.resolve(item.source_file)

        # Reuse method Phase 3 (`update_tts_result`) apa adanya — kontraknya
        # ("simpan path file audio siap-putar + status cache") sama persis
        # dibutuhkan di sini, walau namanya condong ke istilah TTS. Menambah
        # method baru di QueueManager hanya untuk mengganti nama akan
        # menduplikasi logika yang identik tanpa manfaat nyata.
        await self._queue_manager.update_tts_result(
            item.id,
            audio_file_path=audio_file_path,
            cache_hit=cache_hit,
        )
        logger.info(
            "Audio asset diresolusikan untuk item id=%s (cache_hit=%s, file=%s -> %s)",
            item.id,
            cache_hit,
            item.source_file,
            audio_file_path,
        )
