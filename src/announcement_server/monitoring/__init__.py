"""Domain Monitoring (Phase 11).

Menambahkan Metrics KUMULATIF (tidak berkurang meski riwayat queue
di-prune oleh ``queue.max_history``, berbeda dengan ``GET /metrics``
Phase 10 yang murni membaca state registry SAAT INI), serta Rotating
Log/Error Log/Playback Log/Worker Log (lihat ``core/logging.py``).

``MetricsCollector`` (``metrics.py``) memenuhi kontrak ``EventPublisher``
yang sama dengan ``ConnectionManager`` (Phase 9, ``websocket/manager.py``)
— keduanya di-gabung lewat satu fan-out publisher kecil di ``main.py``
tanpa mengubah ``QueueManager``/``PlaybackManager``/``ZoneManager`` sama
sekali (kontrak ``on_event`` tetap satu callable).
"""
