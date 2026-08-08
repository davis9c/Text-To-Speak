"""Queue Manager.

Mengelola siklus hidup item antrean menggunakan ``asyncio.PriorityQueue``
sebagai struktur pengurutan (priority + FIFO), dan sebuah *registry*
(dict di memory) sebagai sumber kebenaran status setiap item.

--------------------------------------------------------------------------
Keputusan desain #1 — Unbounded underlying queue, batas diberlakukan di
level aplikasi:

``asyncio.PriorityQueue`` DIBIARKAN tanpa ``maxsize`` (unbounded). Jika
``maxsize`` diberlakukan langsung pada queue, maka ``put()`` akan
menunggu (blocking-await) saat queue fisik penuh — termasuk saat penuh
oleh item yang SUDAH dibatalkan tapi belum sempat di-dequeue oleh worker
(lihat keputusan #2). Karena ``enqueue()`` memegang lock registry selama
``await queue.put()``, kondisi tsb berpotensi men-deadlock seluruh
manager (semua operasi lain ikut menunggu lock). Sebagai gantinya, batas
antrean (``max_size``) diberlakukan secara logis: menghitung jumlah item
berstatus PENDING pada registry. Ini lebih aman untuk sistem 24/7.

Keputusan desain #2 — Lazy deletion untuk cancel/clear:

``asyncio.PriorityQueue`` tidak mendukung penghapusan item secara
langsung/acak (butuh rebuild heap O(n) dan rawan race condition dengan
worker yang sedang berjalan). Maka ``cancel_item()`` dan ``clear()``
hanya mengubah status item di registry menjadi CANCELLED. Saat worker
men-dequeue item tsb (``dequeue_for_processing``), ia mengecek status di
registry — jika sudah bukan PENDING, item dilewati begitu saja. Trade-off:
entri "hantu" tetap ada sesaat di underlying queue, tapi ini O(1) dan
tidak pernah memblokir.

Keputusan desain #3 — Pruning riwayat (history):

Registry menyimpan SEMUA item (termasuk yang sudah selesai/batal/gagal)
agar bisa ditampilkan lewat ``GET /queue?status=...``. Pada sistem yang
berjalan 24/7 tanpa pruning, ini akan menjadi memory leak. Maka setiap
kali sebuah item mencapai status final, manager memangkas item final
tertua jika jumlah riwayat melebihi ``max_history``. (Penyimpanan riwayat
permanen ke storage eksternal adalah scope Phase 10 - Dashboard/History,
bukan Phase 2.)
Keputusan desain #4 — Event publishing (Phase 9, WebSocket):

``QueueManager`` menerima ``on_event`` opsional (default no-op, lihat
``core/events.py``) yang dipanggil SETELAH lock dilepas pada setiap
perubahan status item (enqueue/dequeue/completed/failed/cancelled/clear).
``QueueManager`` sendiri TIDAK tahu apa-apa soal WebSocket — ia hanya
memanggil sebuah callable generik, memenuhi Dependency Inversion
Principle. Implementasi broadcast sungguhan (``websocket/manager.py``)
disuntikkan oleh ``ZoneManager`` saat membuat instance ini, persis pola
yang sama dengan ``TTSService``/``AudioAssetResolver`` (Phase 3/7).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from announcement_server.core.events import EVENT_FINISHED, EVENT_QUEUE_CHANGED, EventPublisher, noop_event_publisher
from announcement_server.core.exceptions import (
    QueueFullError,
    QueueItemNotCancellableError,
    QueueItemNotFoundError,
)
from announcement_server.queueing.models import (
    FINISHED_STATUSES,
    AnnouncementType,
    QueueItem,
    QueueItemStatus,
    QueuePriority,
)

logger = logging.getLogger(__name__)

# Bobot numerik untuk pengurutan di PriorityQueue. Semakin kecil, semakin
# dulu di-dequeue. Ini satu-satunya tempat pemetaan priority -> bobot
# didefinisikan (single source of truth).
_PRIORITY_WEIGHT: dict[QueuePriority, int] = {
    QueuePriority.URGENT: 0,
    QueuePriority.HIGH: 1,
    QueuePriority.NORMAL: 2,
    QueuePriority.LOW: 3,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _item_event_payload(item: QueueItem, *, reason: str) -> dict:
    """Payload event ringkas untuk satu perubahan item — dipakai di seluruh titik emit di bawah."""
    return {
        "reason": reason,
        "item_id": str(item.id),
        "status": item.status.value,
        "priority": item.priority.value,
        "text": item.text,
    }


class QueueManager:
    """Mengelola antrean pengumuman: enqueue, dequeue, cancel, list, clear."""

    def __init__(self, max_size: int = 100, max_history: int = 1000, *, on_event: EventPublisher = noop_event_publisher) -> None:
        # Tuple berisi (bobot_priority, sequence, item_id_str).
        # `sequence` (counter monotonic) menjamin urutan FIFO untuk item
        # dengan priority sama, sekaligus mencegah Python mencoba
        # membandingkan elemen ketiga (str id) saat dua tuple kebetulan
        # punya (bobot, sequence) yang identik — yang tidak akan pernah
        # terjadi karena sequence selalu unik.
        self._queue: asyncio.PriorityQueue[tuple[int, int, str]] = asyncio.PriorityQueue()
        self._registry: dict[uuid.UUID, QueueItem] = {}
        self._sequence_counter = itertools.count()
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._max_history = max_history
        self._on_event = on_event

    @property
    def max_size(self) -> int:
        return self._max_size

    async def enqueue(
        self,
        text: str,
        priority: QueuePriority,
        *,
        engine: str | None = None,
        voice: str = "default",
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
        announcement_type: AnnouncementType = AnnouncementType.TTS,
        source_file: str | None = None,
        chime_file: str | None = None,
    ) -> QueueItem:
        """Menambahkan item baru ke antrean. Melempar QueueFullError jika penuh.

        Parameter TTS (``voice``/``speed``/``pitch``/``volume``) SENGAJA
        keyword-only dengan default, ditambahkan pada Phase 3 tanpa
        mengubah dua parameter pertama (``text``, ``priority``) yang sudah
        ada sejak Phase 2 — kode/test lama yang memanggil
        ``enqueue(text, priority)`` tetap berjalan tanpa perubahan.

        ``announcement_type``/``source_file`` (Phase 7) mengikuti pola yang
        sama: keyword-only dengan default ``AnnouncementType.TTS``/``None``,
        sehingga seluruh pemanggilan lama (Phase 2-6, selalu TTS) tetap
        berperilaku identik tanpa perubahan.

        ``chime_file`` (opsional) mengikuti pola yang sama persis: keyword-only
        dengan default ``None`` (= tanpa chime) — pemanggilan lama yang tidak
        pernah tahu soal chime tetap berperilaku identik tanpa perubahan.

        ``engine`` (V2 Phase 2) mengikuti pola yang sama persis: keyword-only,
        default ``None`` (= pakai engine default server, lihat
        ``TTSEngineManager``) — seluruh pemanggilan lama yang tidak pernah
        tahu soal multi-engine tetap berperilaku identik dengan V1.
        """
        async with self._lock:
            pending_count = sum(1 for item in self._registry.values() if item.status == QueueItemStatus.PENDING)
            if pending_count >= self._max_size:
                raise QueueFullError(
                    f"Antrean penuh (maksimum {self._max_size} item pending).",
                    details={"max_size": self._max_size, "current_pending": pending_count},
                )

            now = _utcnow()
            item = QueueItem(
                id=uuid.uuid4(),
                text=text,
                priority=priority,
                status=QueueItemStatus.PENDING,
                created_at=now,
                updated_at=now,
                engine=engine,
                voice=voice,
                speed=speed,
                pitch=pitch,
                volume=volume,
                announcement_type=announcement_type,
                source_file=source_file,
                chime_file=chime_file,
            )
            self._registry[item.id] = item

            sequence = next(self._sequence_counter)
            weight = _PRIORITY_WEIGHT[priority]
            await self._queue.put((weight, sequence, str(item.id)))

            logger.info("Item masuk antrean: id=%s priority=%s", item.id, priority.value)
            result = item.model_copy()
        await self._on_event(EVENT_QUEUE_CHANGED, _item_event_payload(result, reason="enqueued"))
        return result

    async def dequeue_for_processing(self) -> QueueItem | None:
        """Dipanggil oleh QueueWorker.

        Menunggu (blocking-await) hingga ada item di queue, lalu menandainya
        PROCESSING. Mengembalikan ``None`` jika item ternyata sudah
        dibatalkan/dihapus sebelum sempat diproses — pemanggil (worker)
        harus lanjut ke iterasi berikutnya, bukan menganggap ini error.
        """
        _weight, _sequence, item_id_str = await self._queue.get()
        item_id = uuid.UUID(item_id_str)
        async with self._lock:
            item = self._registry.get(item_id)
            if item is None or item.status != QueueItemStatus.PENDING:
                self._queue.task_done()
                return None
            item.status = QueueItemStatus.PROCESSING
            item.updated_at = _utcnow()
            result = item.model_copy()
        await self._on_event(EVENT_QUEUE_CHANGED, _item_event_payload(result, reason="processing"))
        return result

    async def update_tts_result(self, item_id: uuid.UUID, *, audio_file_path: str, cache_hit: bool) -> None:
        """Menyimpan hasil sintesis TTS (path file audio + status cache) ke item.

        Ditambahkan pada Phase 3, dipanggil oleh ``TTSQueueProcessor``
        SEBELUM item ditandai selesai oleh worker. Method ini SENGAJA
        TIDAK mengubah ``status`` item — perubahan status tetap sepenuhnya
        menjadi tanggung jawab ``mark_completed``/``mark_failed`` yang
        sudah ada sejak Phase 2 (Single Responsibility), sehingga kontrak
        kedua method tsb tidak perlu diubah sama sekali untuk Phase 3.
        """
        async with self._lock:
            item = self._registry.get(item_id)
            if item is not None:
                item.audio_file_path = audio_file_path
                item.cache_hit = cache_hit
                item.updated_at = _utcnow()

    async def mark_completed(self, item_id: uuid.UUID) -> None:
        """Menandai item selesai diproses. Dipanggil oleh QueueWorker."""
        result: QueueItem | None = None
        async with self._lock:
            item = self._registry.get(item_id)
            if item is not None:
                item.status = QueueItemStatus.COMPLETED
                item.updated_at = _utcnow()
                logger.info("Item selesai diproses: id=%s", item_id)
                result = item.model_copy()
            self._prune_history_locked()
        # `task_done()` hanya untuk item yang benar-benar ter-dequeue (lihat kontrak
        # `dequeue_for_processing()`): memanggilnya untuk item tak dikenal akan
        # membuat hitungan `unfinished_tasks` negatif (ValueError), padahal tidak
        # ada task yang pernah di-get untuk item tsb.
        if result is not None:
            self._queue.task_done()
            await self._on_event(EVENT_QUEUE_CHANGED, _item_event_payload(result, reason="completed"))
            await self._on_event(EVENT_FINISHED, _item_event_payload(result, reason="completed"))

    async def mark_failed(self, item_id: uuid.UUID, error_message: str) -> None:
        """Menandai item gagal diproses. Dipanggil oleh QueueWorker."""
        result: QueueItem | None = None
        async with self._lock:
            item = self._registry.get(item_id)
            if item is not None:
                item.status = QueueItemStatus.FAILED
                item.updated_at = _utcnow()
                item.error_message = error_message
                logger.warning("Item gagal diproses: id=%s error=%s", item_id, error_message)
                result = item.model_copy()
            self._prune_history_locked()
        if result is not None:
            self._queue.task_done()
            await self._on_event(EVENT_QUEUE_CHANGED, _item_event_payload(result, reason="failed"))
            await self._on_event(EVENT_FINISHED, _item_event_payload(result, reason="failed"))

    async def list_items(self, statuses: Iterable[QueueItemStatus] | None = None) -> list[QueueItem]:
        """Mengembalikan salinan item, diurutkan berdasarkan priority lalu waktu masuk.

        ``statuses=None`` mengembalikan seluruh item (termasuk riwayat final
        yang masih tersimpan). Untuk melihat status tertentu saja, berikan
        iterable status (mis. ``{QueueItemStatus.PENDING}``).
        """
        status_set = set(statuses) if statuses is not None else None
        async with self._lock:
            items = list(self._registry.values())
        if status_set is not None:
            items = [i for i in items if i.status in status_set]
        items.sort(key=lambda i: (_PRIORITY_WEIGHT[i.priority], i.created_at))
        return [i.model_copy() for i in items]

    async def get_item(self, item_id: uuid.UUID) -> QueueItem:
        async with self._lock:
            item = self._registry.get(item_id)
        if item is None:
            raise QueueItemNotFoundError(f"Item antrean dengan id {item_id} tidak ditemukan.")
        return item.model_copy()

    async def cancel_item(self, item_id: uuid.UUID) -> QueueItem:
        """Membatalkan item berstatus PENDING. Item yang sudah PROCESSING/final tidak bisa dibatalkan."""
        async with self._lock:
            item = self._registry.get(item_id)
            if item is None:
                raise QueueItemNotFoundError(f"Item antrean dengan id {item_id} tidak ditemukan.")
            if item.status != QueueItemStatus.PENDING:
                raise QueueItemNotCancellableError(
                    f"Item dengan status '{item.status.value}' tidak dapat dibatalkan.",
                    details={"current_status": item.status.value},
                )
            item.status = QueueItemStatus.CANCELLED
            item.updated_at = _utcnow()
            logger.info("Item antrean dibatalkan: id=%s", item_id)
            self._prune_history_locked()
            result = item.model_copy()
        await self._on_event(EVENT_QUEUE_CHANGED, _item_event_payload(result, reason="cancelled"))
        return result

    async def clear(self) -> int:
        """Membatalkan seluruh item PENDING. Mengembalikan jumlah item yang dibatalkan."""
        async with self._lock:
            now = _utcnow()
            cleared = 0
            for item in self._registry.values():
                if item.status == QueueItemStatus.PENDING:
                    item.status = QueueItemStatus.CANCELLED
                    item.updated_at = now
                    cleared += 1
            logger.info("Antrean dibersihkan: %d item dibatalkan", cleared)
            self._prune_history_locked()
        if cleared > 0:
            await self._on_event(EVENT_QUEUE_CHANGED, {"reason": "cleared", "cleared_count": cleared})
        return cleared

    @staticmethod
    def position_of(item_id: uuid.UUID, pending_items_ordered: list[QueueItem]) -> int | None:
        """Menghitung posisi 1-based item di antara item PENDING yang sudah terurut.

        Mengembalikan ``None`` jika item tidak ditemukan pada list (mis.
        item tsb bukan berstatus PENDING).
        """
        for index, item in enumerate(pending_items_ordered, start=1):
            if item.id == item_id:
                return index
        return None

    def _prune_history_locked(self) -> None:
        """Memangkas riwayat item final tertua jika melebihi ``max_history``.

        HARUS dipanggil dalam context ``self._lock`` (nama method diberi
        akhiran ``_locked`` sebagai penanda konvensi).
        """
        finished = [item for item in self._registry.values() if item.status in FINISHED_STATUSES]
        excess = len(finished) - self._max_history
        if excess <= 0:
            return
        finished.sort(key=lambda i: i.updated_at)
        for item in finished[:excess]:
            del self._registry[item.id]
        logger.debug("Riwayat antrean dipangkas: %d item lama dihapus dari memory.", excess)
