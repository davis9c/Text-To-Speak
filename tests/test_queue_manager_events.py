"""Unit test untuk event emission (Phase 9) pada QueueManager.

Melengkapi ``test_queue_manager.py`` (Phase 2, tidak diubah) — fokus di
sini KHUSUS pada perilaku baru: ``on_event`` dipanggil dengan nama event
& payload yang benar pada setiap perubahan status item, dan TIDAK
dipanggil sama sekali jika default (``noop_event_publisher``) dipakai
(perilaku Phase 1-8 tidak berubah).
"""

from __future__ import annotations

import uuid

from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueuePriority


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, dict(data)))


async def test_enqueue_emits_queue_changed() -> None:
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)

    item = await manager.enqueue("Halo", QueuePriority.NORMAL)

    assert len(recorder.events) == 1
    event_type, data = recorder.events[0]
    assert event_type == "queue_changed"
    assert data["reason"] == "enqueued"
    assert data["item_id"] == str(item.id)
    assert data["status"] == "pending"


async def test_dequeue_for_processing_emits_queue_changed() -> None:
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)
    await manager.enqueue("Halo", QueuePriority.NORMAL)
    recorder.events.clear()  # abaikan event dari enqueue, fokus ke dequeue

    item = await manager.dequeue_for_processing()

    assert item is not None
    assert len(recorder.events) == 1
    event_type, data = recorder.events[0]
    assert event_type == "queue_changed"
    assert data["reason"] == "processing"
    assert data["status"] == "processing"


async def test_dequeue_cancelled_item_does_not_emit() -> None:
    """Item yang sudah dibatalkan sebelum sempat di-dequeue TIDAK memicu event
    (bukan perubahan status baru, hanya "hantu" di underlying queue — lihat Keputusan #2)."""
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)
    item = await manager.enqueue("Halo", QueuePriority.NORMAL)
    await manager.cancel_item(item.id)
    recorder.events.clear()

    result = await manager.dequeue_for_processing()

    assert result is None
    assert recorder.events == []


async def test_mark_completed_emits_queue_changed_and_finished() -> None:
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)
    item = await manager.enqueue("Halo", QueuePriority.NORMAL)
    await manager.dequeue_for_processing()
    recorder.events.clear()

    await manager.mark_completed(item.id)

    event_types = [event_type for event_type, _ in recorder.events]
    assert event_types == ["queue_changed", "finished"]
    for _, data in recorder.events:
        assert data["reason"] == "completed"
        assert data["status"] == "completed"


async def test_mark_failed_emits_queue_changed_and_finished() -> None:
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)
    item = await manager.enqueue("Halo", QueuePriority.NORMAL)
    await manager.dequeue_for_processing()
    recorder.events.clear()

    await manager.mark_failed(item.id, "Simulasi gagal")

    event_types = [event_type for event_type, _ in recorder.events]
    assert event_types == ["queue_changed", "finished"]
    for _, data in recorder.events:
        assert data["reason"] == "failed"
        assert data["status"] == "failed"


async def test_mark_completed_unknown_item_does_not_emit() -> None:
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)

    await manager.mark_completed(uuid.uuid4())

    assert recorder.events == []


async def test_cancel_item_emits_queue_changed() -> None:
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)
    item = await manager.enqueue("Halo", QueuePriority.NORMAL)
    recorder.events.clear()

    await manager.cancel_item(item.id)

    assert len(recorder.events) == 1
    event_type, data = recorder.events[0]
    assert event_type == "queue_changed"
    assert data["reason"] == "cancelled"


async def test_clear_emits_single_queue_changed_with_count() -> None:
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)
    await manager.enqueue("Satu", QueuePriority.NORMAL)
    await manager.enqueue("Dua", QueuePriority.NORMAL)
    recorder.events.clear()

    cleared = await manager.clear()

    assert cleared == 2
    assert len(recorder.events) == 1
    event_type, data = recorder.events[0]
    assert event_type == "queue_changed"
    assert data == {"reason": "cleared", "cleared_count": 2}


async def test_clear_with_nothing_pending_does_not_emit() -> None:
    recorder = RecordingEventPublisher()
    manager = QueueManager(on_event=recorder)

    cleared = await manager.clear()

    assert cleared == 0
    assert recorder.events == []


async def test_default_on_event_is_noop_and_does_not_raise() -> None:
    """Tanpa `on_event` (default), seluruh method tetap berjalan normal — perilaku Phase 1-8 tidak berubah."""
    manager = QueueManager()
    item = await manager.enqueue("Halo", QueuePriority.NORMAL)
    await manager.dequeue_for_processing()
    await manager.mark_completed(item.id)
    # Tidak melempar apa pun -> lulus.
