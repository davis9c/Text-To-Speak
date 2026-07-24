"""TTS Queue Processor.

Jembatan antara ``QueueWorker`` (generik, tidak tahu apa-apa soal TTS —
dibangun di Phase 2 dan TIDAK diubah sama sekali di Phase 3) dan
``TTSService`` (murni domain TTS, tidak tahu apa-apa soal Queue).

``QueueWorker`` menerima ``item_processor`` apa pun yang memenuhi kontrak
``Callable[[QueueItem], Awaitable[None]]`` (didefinisikan di
``queueing.worker`` sejak Phase 2). ``TTSQueueProcessor`` di bawah ini
memenuhi kontrak tsb lewat ``__call__``, sehingga bisa langsung dipakai
sebagai pengganti ``default_stub_processor`` tanpa perlu mengubah
``QueueWorker`` — persis seperti yang direncanakan di komentar
``queueing/worker.py`` sejak Phase 2.
"""

from __future__ import annotations

import logging

from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueueItem
from announcement_server.tts.service import TTSService

logger = logging.getLogger(__name__)


class TTSQueueProcessor:
    """Item processor yang menjalankan pipeline TTS untuk setiap item antrean."""

    def __init__(self, tts_service: TTSService, queue_manager: QueueManager) -> None:
        self._tts_service = tts_service
        self._queue_manager = queue_manager

    async def __call__(self, item: QueueItem) -> None:
        """Dipanggil oleh QueueWorker untuk setiap item berstatus PROCESSING.

        Exception apa pun yang dilempar di sini (mis. VoiceNotFoundError,
        TTSEngineNotAvailableError, TTSGenerationError) SENGAJA dibiarkan
        menjalar ke atas, bukan ditangkap di sini — kontrak ini sudah
        ditentukan oleh ``QueueWorker._process_item`` sejak Phase 2, yang
        akan menangkapnya dan menandai item sebagai FAILED beserta pesan
        error-nya.
        """
        result = await self._tts_service.synthesize(
            text=item.text,
            voice=item.voice,
            speed=item.speed,
            pitch=item.pitch,
            volume=item.volume,
        )
        await self._queue_manager.update_tts_result(
            item.id,
            audio_file_path=result.audio_file_path,
            cache_hit=result.cache_hit,
        )
        logger.info(
            "TTS selesai untuk item id=%s (cache_hit=%s, file=%s)",
            item.id,
            result.cache_hit,
            result.audio_file_path,
        )
