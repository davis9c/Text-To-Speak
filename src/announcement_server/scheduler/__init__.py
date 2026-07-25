"""Domain Scheduler (Phase 8).

Memicu pengumuman secara otomatis berbasis waktu — mendukung Daily,
Weekly, dan One Time (lihat ROADMAP.md, contoh: 07.00 -> Bell,
12.00 -> Istirahat, 15.00 -> Pulang).

Modul di sini murni domain (tidak tahu apa-apa soal HTTP):

- ``models.py`` — ``ScheduleRecurrence``, ``AnnouncementSpec`` (isi
  pengumuman yang akan di-enqueue), ``ScheduleEntry`` (satu jadwal), dan
  fungsi murni ``compute_next_run`` (kalkulasi waktu pemicu berikutnya —
  tidak melakukan I/O apa pun, mudah diuji).
- ``manager.py`` — ``SchedulerManager``: registry jadwal (CRUD, pola yang
  sama seperti ``ZoneManager``, Phase 6) + satu background task yang
  memeriksa jadwal jatuh tempo secara berkala, lalu meng-enqueue lewat
  ``QueueManager.enqueue()`` milik zone tujuan (Phase 2/6/7, TIDAK diubah
  atau diduplikasi sama sekali) — SchedulerManager murni "mengetuk pintu"
  antrean yang sudah ada, bukan jalur pemrosesan baru.
"""
