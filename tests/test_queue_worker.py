"""Test untuk QueueWorker: memastikan worker benar-benar mengonsumsi antrean."""

from __future__ import annotations

import asyncio

import pytest

from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import QueueItem, QueueItemStatus, QueuePriority
from announcement_server.queueing.worker import QueueWorker


async def _wait_until(condition, timeout: float = 2.0, interval: float = 0.01) -> None:
    """Helper: polling hingga `condition()` True atau timeout (menghindari sleep tetap yang flaky/lambat)."""
    elapsed = 0.0
    while not condition():
        if elapsed >= timeout:
            raise AssertionError("Timeout menunggu kondisi terpenuhi.")
        await asyncio.sleep(interval)
        elapsed += interval


async def test_worker_processes_item_with_stub_processor() -> None:
    manager = QueueManager(max_size=10, max_history=10)
    item = await manager.enqueue("Halo dunia", QueuePriority.NORMAL)

    worker = QueueWorker(manager)  # pakai default_stub_processor
    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.COMPLETED


async def test_worker_marks_failed_when_processor_raises() -> None:
    manager = QueueManager(max_size=10, max_history=10)
    item = await manager.enqueue("Akan gagal", QueuePriority.NORMAL)

    async def failing_processor(_: QueueItem) -> None:
        raise RuntimeError("Simulasi kegagalan TTS engine")

    worker = QueueWorker(manager, item_processor=failing_processor)
    worker.start()
    try:
        await _wait_until(lambda: manager._registry[item.id].status == QueueItemStatus.FAILED)
    finally:
        await worker.stop()

    result = await manager.get_item(item.id)
    assert result.status == QueueItemStatus.FAILED
    assert result.error_message == "Simulasi kegagalan TTS engine"


async def test_worker_skips_cancelled_item_without_processing() -> None:
    manager = QueueManager(max_size=10, max_history=10)
    cancelled_item = await manager.enqueue("Batal", QueuePriority.NORMAL)
    kept_item = await manager.enqueue("Tetap diproses", QueuePriority.LOW)
    await manager.cancel_item(cancelled_item.id)

    processed_ids: list = []

    async def recording_processor(item: QueueItem) -> None:
        processed_ids.append(item.id)

    worker = QueueWorker(manager, item_processor=recording_processor)
    worker.start()
    try:
        await _wait_until(lambda: manager._registry[kept_item.id].status == QueueItemStatus.COMPLETED)
    finally:
        await worker.stop()

    assert cancelled_item.id not in processed_ids
    assert kept_item.id in processed_ids


async def test_worker_stop_is_graceful_and_idempotent() -> None:
    manager = QueueManager(max_size=10, max_history=10)
    worker = QueueWorker(manager)
    worker.start()
    assert worker.is_running

    await worker.stop()
    assert not worker.is_running

    # Memanggil stop() dua kali tidak boleh error.
    await worker.stop()
