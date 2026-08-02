# TTS V2 — RELEASE CANDIDATE 1 (RC1)

## Tujuan

RC1 bukan fase penambahan fitur.

RC1 adalah proses audit menyeluruh terhadap Core V2 yang telah selesai dibangun.

Target RC1 adalah memastikan bahwa seluruh fondasi V2 siap menjadi platform jangka panjang sebelum pengembangan HTML Client, Remote Audio Endpoint, Browser Player, Desktop Player, dan fitur distribusi audio lainnya.

RC1 hanya boleh:

* audit
* review
* validasi
* identifikasi technical debt
* memperbaiki bug nyata
* memperbaiki inkonsistensi

RC1 bukan tempat menambah fitur besar.

---

# Ruang Lingkup

Core V2 yang menjadi objek audit meliputi:

* TTSEngine
* TTSEngineManager
* EngineFactory
* VoiceProfile
* VoiceRegistry
* Engine Capability
* Multi-Engine
* Piper
* Engine kedua
* REST API
* Queue
* Worker
* Scheduler
* Playback
* Cache
* Metrics
* History
* WebSocket
* Configuration
* Testing

---

# Prinsip RC1

Semua audit harus mengikuti prinsip berikut:

* Source code adalah sumber kebenaran.
* Jangan mengarang masalah.
* Jangan membuat refactor hanya demi kerapian.
* Jangan mengubah perilaku V1 tanpa alasan kuat.
* Jangan menambah dependency kecuali benar-benar diperlukan.
* Jangan membuat breaking change.
* Jangan mengubah kontrak API publik tanpa alasan yang jelas.

---

# Prioritas

Prioritas audit:

1. Correctness
2. Stability
3. Backward Compatibility
4. Maintainability
5. Performance
6. Security
7. Documentation

---

# Tahapan RC1

## RC1-1

Architecture Audit

Audit:

* dependency
* coupling
* cohesion
* abstraction
* SOLID
* duplicate responsibility
* cyclic dependency
* technical debt

---

## RC1-2

API Contract Audit

Audit:

* endpoint
* request schema
* response schema
* status code
* OpenAPI
* error response
* consistency
* backward compatibility

---

## RC1-3

Performance Audit

Audit:

* startup
* lazy loading
* memory
* cache
* scheduler
* websocket
* queue
* playback
* voice discovery
* engine initialization

---

## RC1-4

Error Handling Audit

Audit:

* exception hierarchy
* retry
* timeout
* logging
* API error response
* consistency

---

## RC1-5

Security Audit

Audit:

* validation
* path traversal
* invalid engine
* invalid voice
* scheduler validation
* websocket validation
* configuration exposure
* CORS

---

## RC1-6

Testing Audit

Audit:

* unit test
* integration test
* API test
* scheduler
* queue
* websocket
* engine
* voice registry
* capability

Cari area yang belum memiliki test.

---

## RC1-7

Release Review

Audit:

* README
* OpenAPI
* configuration
* migration V1 → V2
* sample configuration
* roadmap

Pastikan project siap menjadi Release Candidate.

---

# Yang Dilarang

Selama RC1:

* Jangan membuat fitur baru.
* Jangan membuat engine baru.
* Jangan membuat UI.
* Jangan membuat HTML Client.
* Jangan membuat Browser Player.
* Jangan membuat Desktop Player.
* Jangan membuat Audio Endpoint.
* Jangan membuat Emergency Broadcast.
* Jangan membuat MQTT.
* Jangan membuat gRPC.

Semua fitur tersebut berada setelah RC1.

---

# Definisi Selesai

RC1 dianggap selesai apabila:

* seluruh audit selesai
* seluruh bug penting diperbaiki
* seluruh technical debt prioritas tinggi diselesaikan
* seluruh kontrak API stabil
* tidak ada masalah arsitektur besar yang tersisa

Setelah RC1 selesai, Core V2 dianggap stabil dan seluruh pengembangan selanjutnya harus menggunakan Core API tanpa mengubah kontraknya secara breaking.
