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


# --- Invariant: penghitungan inkremental (pending count & pruning via deque) ---
# `_pending_count` dan `_finished_order` adalah state turunan yang harus selalu
# sinkron dengan registry. Test di bawah mengunci sinkronisasi itu lewat
# PERILIKU yang terlihat dari luar (kapasitas antrean & pruning riwayat),
# karena kalau sampai bocor, test yang hanya menjalankan satu jalur saja
# tidak akan pernah menangkapnya.


async def test_pending_capacity_accounts_for_every_exit_path_from_pending(manager: QueueManager) -> None:
    """Kapasitas antrean (max_size) harus mencerminkan jumlah item PENDING yang SEBENARNYA
    ada setelah dequeue, cancel, dan clear — bukan hanya setelah enqueue.

    Ini mengunci `_pending_count` (yang replaces scan O(n) registry per enqueue)
    agar tidak pernah bocor: kalau salah satu jalur di bawah lupa menguranginya,
    antrean akan thinks penuh jauh sebelum batas `max_size` tercapai.
    """
    for i in range(3):
        await manager.enqueue(f"Item {i}", QueuePriority.NORMAL)

    # 1) dequeue_for_processing: item PENDING -> PROCESSING (tidak lagi pending)
    dequeued = await manager.dequeue_for_processing()
    assert dequeued is not None
    counts = await manager.count_by_status()
    assert counts.get(QueueItemStatus.PENDING, 0) == 2
    assert counts.get(QueueItemStatus.PROCESSING, 0) == 1

    # 2) cancel_item: PENDING -> CANCELLED
    to_cancel = await manager.enqueue("Akan dibatalkan", QueuePriority.NORMAL)
    await manager.cancel_item(to_cancel.id)
    counts = await manager.count_by_status()
    assert counts.get(QueueItemStatus.PENDING, 0) == 2
    assert counts.get(QueueItemStatus.CANCELLED, 0) == 1

    # 3) clear(): semua PENDING tersisa -> CANCELLED
    cleared = await manager.clear()
    assert cleared == 2
    counts = await manager.count_by_status()
    assert counts.get(QueueItemStatus.PENDING, 0) == 0

    # Semua slot pending kini kosong -> manager harus bisa menerima item lagi
    # sampai max_size (5) TANPA salah menduga "penuh" karena counter nyangkut.
    for i in range(5):
        await manager.enqueue(f"Setelah dibersihkan {i}", QueuePriority.NORMAL)
    counts = await manager.count_by_status()
    assert counts.get(QueueItemStatus.PENDING, 0) == 5
    with pytest.raises(QueueFullError):
        await manager.enqueue("Harus gagal", QueuePriority.NORMAL)

async def test_count_by_status_matches_list_items(manager: QueueManager) -> None:
    """`count_by_status()` (yang dipakai dashboard) harus konsisten dengan `list_items()`."""
    first = await manager.enqueue("Pending", QueuePriority.NORMAL)
    await manager.enqueue("Juga pending", QueuePriority.LOW)
    processing = await manager.enqueue("Diproses", QueuePriority.URGENT)
    await manager.dequeue_for_processing()  # memproses item URGENT (pertama)
    cancelled = await manager.enqueue("Dibatalkan", QueuePriority.HIGH)
    await manager.cancel_item(cancelled.id)

    items = await manager.list_items()
    expected: dict[QueueItemStatus, int] = {}
    for item in items:
        expected[item.status] = expected.get(item.status, 0) + 1

    counts = await manager.count_by_status()
    assert counts == expected
    assert counts == {
        QueueItemStatus.PENDING: 2,
        QueueItemStatus.PROCESSING: 1,
        QueueItemStatus.CANCELLED: 1,
    }
    # Tiap item terhitung tepat satu kali (tidak ada yang terlewat/dihitung dua kali).
    assert sum(counts.values()) == len(items) == 4
    assert {i.id for i in items} == {first.id, processing.id, cancelled.id, items[3].id}


async def test_count_by_status_omits_zero_count_statuses(manager: QueueManager) -> None:
    """Hanya status yang jumlahnya > 0 yang muncul — dipakai `GET /metrics` yang
    harus mengembalikan `{}` (bukan semua status bernilai 0) saat antrean kosong."""
    assert await manager.count_by_status() == {}

    await manager.enqueue("Satu", QueuePriority.NORMAL)
    counts = await manager.count_by_status()
    assert counts == {QueueItemStatus.PENDING: 1}


async def test_pruning_keeps_newest_items_and_frees_slots() -> None:
    """Setelah pruning, registry hanya boleh berisi `max_history` item final yang
    PALING BARU, dan item yang dipangkas tidak boleh muncul lagi di listing."""
    manager = QueueManager(max_size=100, max_history=3)
    completed_ids = []
    for i in range(8):
        item = await manager.enqueue(f"Item {i}", QueuePriority.NORMAL)
        await manager.dequeue_for_processing()
        await manager.mark_completed(item.id)
        completed_ids.append(item.id)

    remaining = await manager.list_items()
    assert len(remaining) == 3
    assert {i.id for i in remaining} == set(completed_ids[-3:])  # 3 yang terbaru

    # Item yang sudah dipangkas benar-benar hilang (bukan sekadar disembunyikan),
    # dan slot riwayat yang dibebaskan bisa dipakai lagi oleh item baru.
    fresh = await manager.enqueue("Baru", QueuePriority.NORMAL)
    await manager.dequeue_for_processing()
    await manager.mark_completed(fresh.id)
    remaining_ids = {i.id for i in await manager.list_items()}
    assert len(remaining_ids) == 3
    assert fresh.id in remaining_ids


async def test_list_items_recent_returns_newest_first_respecting_limit(manager: QueueManager) -> None:
    """`list_items_recent()` (yang dipakai `GET /history`) mengembalikan item
    terbaru lebih dulu dan tidak melebihi `limit`."""
    done = []
    for i in range(4):
        item = await manager.enqueue(f"Item {i}", QueuePriority.NORMAL)
        await manager.dequeue_for_processing()
        await manager.mark_completed(item.id)
        done.append(item)

    recent = await manager.list_items_recent(limit=2)
    assert len(recent) == 2
    assert [i.id for i in recent] == [done[3].id, done[2].id]  # terbaru dulu

    # Semua item di fixture ini berstatus final, jadi difilter status pun harus
    # tetap memberi hasil yang sama; memfilter ke PENDING harus mengembalikan [].
    from announcement_server.queueing.models import FINISHED_STATUSES

    assert [i.id for i in await manager.list_items_recent(statuses=FINISHED_STATUSES, limit=2)] == [done[3].id, done[2].id]
    assert await manager.list_items_recent(statuses={QueueItemStatus.PENDING}, limit=10) == []


async def test_list_items_recent_agrees_with_full_sort(manager: QueueManager) -> None:
    """Top-k per zone harus menghasilkan jawaban yang sama dengan mengurutkan
    seluruh riwayat lalu memotongnya (dasar dari optimization `GET /history`)."""
    import time as _time

    done = []
    for i in range(6):
        item = await manager.enqueue(f"Item {i}", QueuePriority.NORMAL)
        await manager.dequeue_for_processing()
        await manager.mark_completed(item.id)
        done.append(item)
        _time.sleep(0.002)  # pastikan updated_at benar-benar berbeda

    full = await manager.list_items()
    full.sort(key=lambda i: i.updated_at, reverse=True)
    for limit in (1, 3, 6, 50):
        expected = [i.id for i in full[:limit]]
        actual = [i.id for i in await manager.list_items_recent(limit=limit)]
        assert actual == expected, f"limit={limit}"
