"""Domain Multi Zone (Phase 6).

Berisi model ``Zone`` (metadata: nama, enabled, device, volume) dan
``ZoneManager`` yang mengorkestrasi banyak "jalur audio" independen.
Setiap Zone membungkus komponen yang SUDAH ADA sejak fase-fase
sebelumnya — TANPA duplikasi kelas:

- ``QueueManager``  (Phase 2) — satu instance per zone, antrean independen.
- ``QueueWorker``   (Phase 2) — satu instance per zone, background task independen.
- ``PlaybackManager`` (Phase 4) — satu instance per zone, output audio independen
  (memakai ulang ``AudioDeviceManager`` yang di-share, karena enumerasi device
  bersifat stateless dan sama untuk seluruh zone).
- ``TTSQueueProcessor`` (Phase 3) — satu instance per zone (pola yang sama
  seperti dipakai untuk zone "main" sejak Phase 5), tapi berbagi satu
  ``TTSService`` (Phase 3) di seluruh zone — engine TTS & cache audio TIDAK
  digandakan, karena keduanya independen dari konsep zone.
- ``AnnouncementPipelineProcessor`` (Phase 5) — satu instance per zone,
  dengan ``volume_gain`` (Phase 6) sesuai volume masing-masing zone.

Modul ini murni domain (tidak tahu apa-apa soal HTTP) — layer HTTP ada di
``api/v1/zones.py`` + ``schemas/zones.py``.
"""
