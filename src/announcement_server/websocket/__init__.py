"""Domain WebSocket (Phase 9).

Endpoint ``/ws/status`` (lihat ``api/v1/websocket.py``) mem-broadcast
perubahan status secara real-time — TANPA POLLING (sesuai ROADMAP.md):
Queue Changed, Speaking, Idle, Pause, Resume, Finished.

``ConnectionManager`` (``manager.py``) murni infrastruktur pengiriman
pesan ke client yang terhubung — TIDAK tahu apa-apa soal Queue/Playback.
Ia hanya mengimplementasikan kontrak ``EventPublisher``
(``core/events.py``), yang disuntikkan ke ``QueueManager``/``PlaybackManager``
lewat ``ZoneManager`` (Phase 6) — persis pola dependency injection yang
sama dengan ``TTSService``/``AudioAssetResolver`` di fase-fase sebelumnya.
"""
