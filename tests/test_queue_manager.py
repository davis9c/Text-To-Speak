"""Unit test untuk QueueManager (tanpa HTTP, tanpa worker).

Test di file ini fokus pada logika murni queue: urutan priority, FIFO
untuk priority sama, cancel, clear, dan error handling. Worker sengaja
TIDAK dijalankan di sini supaya urutan dequeue bisa diverifikasi secara
deterministik.
"""

from __future__ import annotations

import uuid

import pytest

from announcement_server.core.exceptions import (
    QueueFullError,
    QueueItemNotCancellableError,
    QueueItemNotFoundError,
)
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueueItemStatus, QueuePriority


@pytest.fixture()
def manager() -> QueueManager:
    return QueueManager(max_size=5, max_history=10)


async def test_enqueue_sets_status_pending(manager: QueueManager) -> None:
    item = await manager.enqueue("Halo", QueuePriority.NORMAL)
    assert item.status == QueueItemStatus.PENDING
    assert item.priority == QueuePriority.NORMAL
    assert item.error_message is None


async def test_priority_order_urgent_before_low(manager: QueueManager) -> None:
    low_item = await manager.enqueue("Pengumuman biasa", QueuePriority.LOW)
    urgent_item = await manager.enqueue("Darurat!", QueuePriority.URGENT)

    first = await manager.dequeue_for_processing()
    second = await manager.dequeue_for_processing()

    assert first is not None and second is not None
    assert first.id == urgent_item.id
    assert second.id == low_item.id


async def test_fifo_order_for_same_priority(manager: QueueManager) -> None:
    first_in = await manager.enqueue("Pertama", QueuePriority.NORMAL)
    second_in = await manager.enqueue("Kedua", QueuePriority.NORMAL)
    third_in = await manager.enqueue("Ketiga", QueuePriority.NORMAL)

    dequeued_ids = []
    for _ in range(3):
        item = await manager.dequeue_for_processing()
        assert item is not None
        dequeued_ids.append(item.id)

    assert dequeued_ids == [first_in.id, second_in.id, third_in.id]


async def test_queue_full_raises_error(manager: QueueManager) -> None:
    for i in range(5):
        await manager.enqueue(f"Item {i}", QueuePriority.NORMAL)

    with pytest.raises(QueueFullError):
        await manager.enqueue("Item ke-6, seharusnya gagal", QueuePriority.NORMAL)


async def test_cancel_pending_item(manager: QueueManager) -> None:
    item = await manager.enqueue("Akan dibatalkan", QueuePriority.NORMAL)
    cancelled = await manager.cancel_item(item.id)
    assert cancelled.status == QueueItemStatus.CANCELLED


async def test_cancelled_item_is_skipped_by_dequeue(manager: QueueManager) -> None:
    cancelled_item = await manager.enqueue("Batal", QueuePriority.HIGH)
    kept_item = await manager.enqueue("Tetap ada", QueuePriority.LOW)
    await manager.cancel_item(cancelled_item.id)

    first_dequeue = await manager.dequeue_for_processing()
    assert first_dequeue is None  # item yang dibatalkan dilewati, bukan error

    second_dequeue = await manager.dequeue_for_processing()
    assert second_dequeue is not None
    assert second_dequeue.id == kept_item.id


async def test_cancel_non_pending_item_raises_conflict(manager: QueueManager) -> None:
    item = await manager.enqueue("Akan diproses", QueuePriority.NORMAL)
    await manager.dequeue_for_processing()  # status -> PROCESSING

    with pytest.raises(QueueItemNotCancellableError):
        await manager.cancel_item(item.id)


async def test_cancel_unknown_id_raises_not_found(manager: QueueManager) -> None:
    with pytest.raises(QueueItemNotFoundError):
        await manager.cancel_item(uuid.uuid4())


async def test_clear_cancels_all_pending_only(manager: QueueManager) -> None:
    pending_item = await manager.enqueue("Pending", QueuePriority.NORMAL)
    processing_item = await manager.enqueue("Akan diproses", QueuePriority.HIGH)
    await manager.dequeue_for_processing()  # processing_item -> PROCESSING

    cleared_count = await manager.clear()

    assert cleared_count == 1
    pending_after = await manager.get_item(pending_item.id)
    processing_after = await manager.get_item(processing_item.id)
    assert pending_after.status == QueueItemStatus.CANCELLED
    assert processing_after.status == QueueItemStatus.PROCESSING


async def test_mark_completed_updates_status(manager: QueueManager) -> None:
    item = await manager.enqueue("Selesai nanti", QueuePriority.NORMAL)
    await manager.dequeue_for_processing()
    await manager.mark_completed(item.id)

    completed = await manager.get_item(item.id)
    assert completed.status == QueueItemStatus.COMPLETED


async def test_mark_failed_records_error_message(manager: QueueManager) -> None:
    item = await manager.enqueue("Akan gagal", QueuePriority.NORMAL)
    await manager.dequeue_for_processing()
    await manager.mark_failed(item.id, "TTS engine timeout")

    failed = await manager.get_item(item.id)
    assert failed.status == QueueItemStatus.FAILED
    assert failed.error_message == "TTS engine timeout"


async def test_position_of_reflects_priority_order(manager: QueueManager) -> None:
    await manager.enqueue("Normal 1", QueuePriority.NORMAL)
    urgent_item = await manager.enqueue("Urgent", QueuePriority.URGENT)

    pending_items = await manager.list_items(statuses={QueueItemStatus.PENDING})
    position = manager.position_of(urgent_item.id, pending_items)

    assert position == 1  # urgent selalu di depan meskipun masuk belakangan


async def test_history_pruned_beyond_max_history() -> None:
    manager = QueueManager(max_size=100, max_history=2)
    for i in range(5):
        item = await manager.enqueue(f"Item {i}", QueuePriority.NORMAL)
        await manager.dequeue_for_processing()
        await manager.mark_completed(item.id)

    all_items = await manager.list_items()
    finished = [i for i in all_items if i.status == QueueItemStatus.COMPLETED]
    assert len(finished) == 2  # dipangkas, hanya 2 riwayat terbaru yang tersisa
