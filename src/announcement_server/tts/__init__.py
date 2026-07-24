"""Domain TTS Engine (Phase 3).

Berisi interface engine (Strategy Pattern), implementasi Piper, factory
untuk memilih engine berdasarkan config, post-processing audio generik
(volume/pitch), cache berbasis SHA256, dan `TTSService` sebagai orkestrator
yang menyatukan semuanya.

Modul ini murni domain TTS — tidak tahu apa-apa soal HTTP maupun Queue
System. Jembatan ke Queue System ada di
``announcement_server.queueing.tts_processor.TTSQueueProcessor``.
"""
