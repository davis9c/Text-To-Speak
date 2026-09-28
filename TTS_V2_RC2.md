# TTS V2 — Release Candidate 2 (RC2)

## Tujuan

RC2 merupakan tahap penyempurnaan Platform Multi-Engine.

RC1 telah berhasil membangun fondasi multi-engine yang stabil melalui:

* TTSEngine
* TTSEngineManager
* EngineFactory
* Voice Registry
* Engine Capability
* Multi-Engine API
* Multi-Engine Configuration
* Multi-Engine Discovery

RC2 tidak lagi berfokus pada penambahan engine baru.

Fokus utama RC2 adalah memastikan Core benar-benar siap menjadi platform multi-engine yang stabil, mudah dikembangkan, dan tidak memerlukan perubahan arsitektur ketika engine baru ditambahkan di masa depan.

---

# Target RC2

RC2 berfokus pada penyempurnaan platform.

Target utama:

* Engine Lifecycle
* Engine Health
* Dynamic Engine Management
* Per-Engine Metrics
* Multi-Engine Validation
* Platform Audit
* Release Readiness

---

# Prinsip RC2

Seluruh perubahan harus mengikuti prinsip berikut.

## Engine Agnostic

Core tidak boleh memiliki ketergantungan terhadap engine tertentu.

Seluruh engine harus diperlakukan sama melalui kontrak `TTSEngine`.

Core tidak boleh mengenali:

* Piper
* eSpeak NG
* Kokoro
* XTTS
* StyleTTS
* maupun engine lainnya.

---

## Open / Closed Principle

Menambahkan engine baru tidak boleh mengubah:

* Queue
* Scheduler
* Playback
* REST API
* WebSocket
* Cache
* Metrics
* HTML Client (nantinya)

Penambahan engine hanya dilakukan melalui implementasi `TTSEngine`.

---

## Backward Compatibility

Seluruh API RC1 tetap berlaku.

Seluruh payload V1 tetap berlaku.

Tidak boleh ada breaking change.

---

## Stable Core

RC2 bukan redesign Core.

RC2 hanya menyempurnakan platform.

---

# Phase RC2

---

# RC2-1

## Engine Lifecycle

Target:

Membangun lifecycle engine yang konsisten.

Fokus:

* initialize()
* shutdown()
* reload()
* refresh()

Audit:

* startup
* shutdown
* resource cleanup
* lifecycle consistency

Output:

Seluruh engine memiliki lifecycle yang seragam.

---

# RC2-2

## Engine Health & Diagnostics

Target:

Setiap engine mempunyai status kesehatan yang nyata.

Contoh informasi:

* initialized
* healthy
* unavailable
* last error
* loaded voices
* last reload
* startup status

Output:

Health engine dapat dipantau tanpa melihat implementasi engine.

---

# RC2-3

## Dynamic Engine Management

Target:

Engine dapat dikelola secara dinamis.

Contoh:

* refresh voice
* reload configuration
* reload engine

Bukan hot reload model.

Bukan plugin system.

Tujuannya adalah menyempurnakan lifecycle.

---

# RC2-4

## Per Engine Metrics

Target:

Setiap engine memiliki metrics sendiri.

Contoh:

* synthesis count
* success
* failure
* timeout
* average latency
* cache hit
* cache miss

Metrics harus tetap engine-agnostic.

---

# RC2-5

## Multi-Engine Validation

Target:

Membuktikan bahwa Core benar-benar engine agnostic.

Validasi:

* Queue tidak berubah
* Scheduler tidak berubah
* Playback tidak berubah
* REST API tidak berubah
* Cache tetap engine-aware

Gunakan dummy engine bila diperlukan.

Jika penambahan engine baru masih membutuhkan perubahan Core, maka phase ini belum selesai.

---

# RC2-6

## Platform Audit

Audit seluruh platform multi-engine.

Fokus:

* abstraction
* dependency
* scalability
* maintainability
* lifecycle
* metrics
* diagnostics

Perbaiki hanya masalah nyata.

Jangan redesign ulang.

---

# RC2-7

## Release Readiness

Review akhir RC2.

Checklist:

* Engine Lifecycle
* Health
* Diagnostics
* Metrics
* Voice Refresh
* Multi-Engine Validation
* Testing
* Documentation

Tujuan akhir:

Menentukan apakah Platform Multi-Engine sudah siap menjadi fondasi jangka panjang.

---

# Yang Tidak Masuk RC2

RC2 tidak mencakup:

* HTML Client
* Browser Audio Endpoint
* Desktop Audio Endpoint
* Emergency Broadcast
* Streaming Audio
* Cluster
* Authentication
* Authorization
* Plugin Marketplace

---

# Engine yang Digunakan

RC2 tetap menggunakan engine yang sudah tersedia.

Minimal:

* Piper
* eSpeak NG

Engine lain hanya menjadi acuan desain.

Tidak wajib diimplementasikan pada RC2.

---

# Definisi Selesai

RC2 dianggap selesai apabila:

* Core benar-benar engine agnostic.
* Lifecycle seluruh engine konsisten.
* Health engine tersedia.
* Metrics tersedia.
* Dynamic management selesai.
* Seluruh audit RC2 selesai.
* Tidak ada breaking change terhadap RC1.

Setelah RC2 selesai, roadmap akan dilanjutkan ke **RC3 (Production Readiness)** sebelum menuju rilis stabil **v2.0.0**.
