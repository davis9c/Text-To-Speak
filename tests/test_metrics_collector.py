"""Unit test untuk MetricsCollector (Phase 11 — Monitoring)."""

from __future__ import annotations

from announcement_server.monitoring.metrics import MetricsCollector


async def test_record_counts_event_types() -> None:
    collector = MetricsCollector()

    await collector.record("queue_changed", {"reason": "enqueued"})
    await collector.record("queue_changed", {"reason": "processing"})
    await collector.record("speaking", {"file": "a.wav"})

    snapshot = collector.snapshot()
    assert snapshot["events"]["queue_changed"] == 2
    assert snapshot["events"]["speaking"] == 1


async def test_record_tracks_finished_reason_breakdown() -> None:
    collector = MetricsCollector()

    await collector.record("finished", {"reason": "completed"})
    await collector.record("finished", {"reason": "completed"})
    await collector.record("finished", {"reason": "failed"})

    snapshot = collector.snapshot()
    assert snapshot["events"]["finished"] == 3
    assert snapshot["finished_by_reason"] == {"completed": 2, "failed": 1}


async def test_finished_event_without_reason_does_not_crash() -> None:
    collector = MetricsCollector()
    await collector.record("finished", {})
    snapshot = collector.snapshot()
    assert snapshot["events"]["finished"] == 1
    assert snapshot["finished_by_reason"] == {}


def test_snapshot_empty_initially() -> None:
    collector = MetricsCollector()
    snapshot = collector.snapshot()
    assert snapshot == {"events": {}, "finished_by_reason": {}}


async def test_snapshot_returns_independent_copy() -> None:
    """Mengubah dict hasil snapshot() tidak boleh memengaruhi state internal collector."""
    collector = MetricsCollector()
    await collector.record("idle", {})

    snapshot = collector.snapshot()
    snapshot["events"]["idle"] = 999

    assert collector.snapshot()["events"]["idle"] == 1
