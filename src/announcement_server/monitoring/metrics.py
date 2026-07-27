"""Metrics Collector (Phase 11 — Monitoring).

Menghitung counter KUMULATIF sejak server start — TIDAK terpengaruh
``queue.max_history`` (berbeda dengan ``GET /metrics`` Phase 10, yang
murni agregasi dari registry queue SAAT INI). Memenuhi kontrak
``EventPublisher`` (``core/events.py``) persis seperti
``ConnectionManager.broadcast`` (Phase 9) — disuntikkan ke
``ZoneManager`` lewat fan-out publisher di ``main.py``, tanpa mengubah
``QueueManager``/``PlaybackManager`` sama sekali.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from announcement_server.core.events import EVENT_FINISHED


def get_process_memory_mb() -> float | None:
    """Mengembalikan penggunaan memori RSS proses saat ini dalam MB (Phase 14 — Memory Leak Check).

    ``None`` jika ``psutil`` tidak terpasang — graceful degradation, sama
    seperti dependensi opsional lain (Piper/ffmpeg) di project ini. Pantau
    nilainya lewat GET /metrics dari waktu ke waktu untuk mendeteksi
    kebocoran memori (RSS yang terus naik tanpa henti).
    """
    try:
        import psutil
    except ImportError:
        return None
    process = psutil.Process()
    return process.memory_info().rss / (1024 * 1024)


class MetricsCollector:
    """Counter kumulatif per jenis event + per alasan `finished` (completed/failed)."""

    def __init__(self) -> None:
        self._event_counts: dict[str, int] = defaultdict(int)
        self._finished_reason_counts: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def record(self, event_type: str, data: dict) -> None:
        """Memenuhi kontrak ``EventPublisher`` — dipanggil untuk SETIAP event Queue/Playback (Phase 9)."""
        async with self._lock:
            self._event_counts[event_type] += 1
            if event_type == EVENT_FINISHED:
                reason = data.get("reason")
                if reason:
                    self._finished_reason_counts[reason] += 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        """Salinan counter saat ini — aman dibaca kapan saja tanpa lock (dict baru, bukan referensi)."""
        return {
            "events": dict(self._event_counts),
            "finished_by_reason": dict(self._finished_reason_counts),
        }
