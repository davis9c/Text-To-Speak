"""Domain Queue System (Phase 2).

Berisi model, manager, dan worker untuk antrean pengumuman. Modul ini
sengaja dipisah dari layer HTTP (``api/``) agar logika queue murni
(business logic) tidak terikat pada FastAPI dan mudah dites secara
independen maupun dipakai ulang oleh komponen lain (mis. Scheduler pada
Phase 8 yang akan memanggil ``QueueManager.enqueue`` secara terprogram).
"""
