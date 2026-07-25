"""Domain Announcement Engine (Phase 7).

Selain TTS (Phase 3), server dapat memutar file audio yang SUDAH ADA di
disk (bell, alarm, jingle, atau file WAV/MP3 apa pun) — dipilih lewat
``type`` pada ``POST /speak``/``POST /zones/{name}/speak``:

```json
{"type": "tts", "text": "Nomor antrean A001"}
```
atau
```json
{"type": "audio", "file": "sounds/bell.mp3"}
```

Modul di sini murni domain (tidak tahu apa-apa soal HTTP/Queue):

- ``asset_resolver.py`` — ``AudioAssetResolver``: memvalidasi & (jika
  perlu) mengonversi file audio statis ke WAV lewat ``ffmpeg``, dengan
  cache hasil konversi (mirip ``tts/cache.py``, Phase 3).
- ``source_processor.py`` — ``AnnouncementSourceProcessor``: item
  processor Stage 2 ("Cache/Generate") yang men-dispatch ke
  ``TTSQueueProcessor`` (Phase 3, TIDAK diubah) atau ``AudioAssetResolver``
  di atas berdasarkan ``item.announcement_type`` — disuntikkan ke
  ``AnnouncementPipelineProcessor`` (Phase 5) SEBAGAI GANTI
  ``TTSQueueProcessor`` langsung, tanpa mengubah satu baris pun kode
  Phase 5 (kontraknya sama persis: ``ItemProcessor``).
"""
