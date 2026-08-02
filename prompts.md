# V2 PHASE 1 — PROJECT ANALYSIS & V1 BASELINE
Kita melanjutkan project **Text-To-Speak Announcement Server V1** yang sudah final.
Saya juga memberikan `TTS_V2_ROADMAP.md` sebagai arah pengembangan V2.
Source code / ZIP project V1 yang sudah diberikan sebelumnya adalah **sumber kebenaran utama**.
## TUJUAN PHASE
Phase ini **HANYA ANALISIS**.
Pahami implementasi V1 secara menyeluruh agar Phase 2 dapat merancang arsitektur Multi-Engine TTS tanpa merusak behavior V1.
**Jangan melakukan implementasi.**
---
## YANG HARUS DIPERIKSA
Telusuri source code aktual, terutama:
### Project Architecture
* struktur folder
* entry point
* konfigurasi
* dependency
* service/module utama
* dependency antar module
### TTS
Pahami alur aktual:
```text
Request
  ↓
Queue
  ↓
Worker
  ↓
TTS Engine
  ↓
Voice / Model
  ↓
Audio Cache
  ↓
Playback
```
Cari tahu secara aktual:
* bagaimana text masuk ke TTS
* bagaimana TTS engine dipanggil
* bagaimana Piper digunakan
* bagaimana model voice ditemukan
* bagaimana voice dipilih
* bagaimana parameter speed/pitch/volume diproses
* format audio output
* cache mechanism
* cache key
* error handling
* lifecycle engine
### Voice
Identifikasi mekanisme voice V1:
* voice ID
* voice name
* language
* gender jika tersedia
* model
* model path
* sample rate
* metadata
* konfigurasi voice
* discovery voice jika tersedia
Jangan mengubah mekanisme tersebut.
### Queue / Worker / Playback
Pahami dependency antara:
```text
Queue
  ↓
Worker
  ↓
TTS
  ↓
Cache
  ↓
Playback
```
Identifikasi bagian yang bergantung langsung pada Piper.
### API
Periksa endpoint aktual yang berhubungan dengan:
* `/speak`
* TTS
* voice
* engine jika sudah ada
* queue
* status
Catat secara internal:
* method
* path
* request
* response
* validation
* error
Jangan membuat endpoint baru.
### Dependency
Identifikasi dependency yang:
* khusus Piper
* khusus TTS
* core application
* audio/playback
* API
* testing
Tentukan bagian mana yang terlalu erat dengan Piper.
---
# ANALISIS KESIAPAN MULTI-ENGINE
Berdasarkan source code aktual, tentukan:
1. Apakah V1 sudah memiliki abstraction TTS Engine?
2. Jika ada, bagaimana interface/kontraknya?
3. Jika belum ada, bagian mana yang perlu diabstraksikan?
4. Bagian mana yang aman diubah pada Phase 2?
5. Bagian mana yang harus tetap kompatibel dengan V1?
6. Apakah Queue/Worker perlu mengetahui engine?
7. Apakah cache perlu mempertimbangkan engine + voice?
8. Bagaimana Voice Profile sebaiknya dipisahkan dari implementasi Piper?
9. Apakah API `/speak` saat ini sudah siap menerima engine/voice secara eksplisit?
10. Risiko terbesar ketika menambahkan engine kedua.
**Jangan memperbaiki masalah tersebut sekarang.**
---
# TARGET V2
Gunakan konsep berikut hanya sebagai target arsitektur:
```text
TTS Engine Manager
        │
        ├── Piper
        ├── Engine 2
        ├── Engine 3
        └── ...
              │
        Voice Registry
              │
        TTS Generation
```
Prioritas V2:
1. Open-source
2. Offline jika memungkinkan
3. Windows compatible
4. Multilingual
5. Kualitas suara
6. CPU/GPU practicality
7. Model/voice mudah dikelola
8. Lisensi jelas
**Belum perlu memilih atau mengimplementasikan engine kedua pada Phase 1.**
Piper tetap menjadi engine V1 yang harus dipertahankan.
---
# ATURAN KETAT
Jangan:
* mengubah source code
* membuat file
* menghapus file
* menambah dependency
* membuat engine baru
* membuat Voice Registry
* membuat Engine Registry
* membuat API baru
* mengubah API V1
* refactor
* membuat UI
* mengubah client
* commit
* push
Jika menemukan masalah V1, **catat saja**.
Jangan memperbaikinya.
---
# OUTPUT
Jangan tampilkan hasil eksplorasi source code secara panjang.
Berikan ringkasan maksimal **8 poin**:
1. Arsitektur TTS V1
2. Implementasi Piper saat ini
3. Mekanisme voice saat ini
4. Mekanisme cache
5. Hubungan Queue → Worker → TTS → Playback
6. Ketergantungan code terhadap Piper
7. Kesiapan V1 untuk Multi-Engine
8. Rekomendasi Phase 2
Jangan menulis kode.
Jangan membuat file.
Jangan mengubah file.
Setelah selesai, **STOP dan tunggu instruksi Phase 2.**


# V2 PHASE 2 — MULTI-ENGINE ARCHITECTURE

Lanjutkan dari hasil **V2 Phase 1**.

Phase 1 telah memastikan bahwa V1 sudah memiliki:

* `TTSEngine` abstraction
* `EngineFactory` registry
* `TTSService`
* Piper sebagai implementation
* cache key sudah mencakup `engine`
* Queue/Worker tidak bergantung langsung pada Piper

Sekarang implementasikan **fondasi Multi-Engine**, tetapi **belum menambahkan engine TTS baru**.

## TUJUAN

Ubah arsitektur dari:

```text
1 Server
   ↓
1 TTSService
   ↓
1 Engine
```

menjadi:

```text
Server
   ↓
TTS Engine Manager
   ├── Piper
   ├── Future Engine A
   └── Future Engine B
```

Engine dapat dipilih **per request / QueueItem**.

Piper harus tetap menjadi default dan behavior V1 harus tetap kompatibel.

---

# IMPLEMENTASI

## 1. TTSEngine

Pertahankan kontrak `TTSEngine` yang sudah ada.

Jangan mengubah interface secara tidak perlu.

Jika tidak ada alasan kuat, pertahankan:

```text
async synthesize(text, voice, speed) -> bytes
```

Jangan menambahkan parameter engine ke dalam `TTSEngine.synthesize()`.

Engine selection adalah tanggung jawab layer di atas engine.

---

## 2. EngineFactory

Pertahankan `EngineFactory` sebagai registry/builder.

Jangan menggantinya dengan mekanisme baru.

EngineFactory tetap bertanggung jawab membuat instance engine.

---

## 3. TTSEngineManager

Buat layer `TTSEngineManager` yang:

* memuat beberapa engine
* menggunakan `EngineFactory`
* menyimpan instance engine yang tersedia
* dapat mengambil engine berdasarkan ID/name
* mengetahui engine default
* memberikan error yang jelas jika engine tidak tersedia

Konsep:

```text
TTSEngineManager
├── piper
├── future_engine_1
└── future_engine_2
```

Manager tidak boleh berisi logic spesifik Piper.

---

## 4. Configuration

Pertahankan konfigurasi V1 yang sudah ada agar tetap valid.

Konfigurasi V1:

```text
tts.engine
```

tetap berarti **default engine**.

Jangan memaksa user mengubah konfigurasi lama.

Jika diperlukan konfigurasi multi-engine, buat struktur yang:

* backward-compatible
* mudah dibaca
* mudah diperluas
* tidak menghapus konfigurasi V1

Jangan menambahkan engine kedua hanya untuk menguji arsitektur.

Piper tetap satu-satunya engine yang aktif setelah Phase 2.

---

# 5. REQUEST ENGINE SELECTION

Tambahkan `engine` secara **opsional** pada request TTS jika struktur V1 memungkinkan.

Contoh konsep:

```json
{
  "text": "Hello",
  "engine": "piper",
  "voice": "en_US-lessac-medium"
}
```

Jika `engine` tidak diberikan:

```text
request.engine
     ↓
default engine
```

Behavior lama harus tetap bekerja.

Artinya request V1 seperti:

```json
{
  "text": "Hello",
  "voice": "en_US-lessac-medium"
}
```

tetap menghasilkan output yang sama seperti V1.

---

# 6. QUEUE ITEM

Tambahkan `engine` secara optional pada `QueueItem` jika diperlukan untuk mempertahankan pilihan engine sampai item diproses.

Pastikan:

```text
HTTP Request
    ↓
QueueItem
    ↓
Worker
    ↓
TTSQueueProcessor
    ↓
TTSService / EngineManager
    ↓
Selected Engine
```

Engine selection harus tetap tersedia ketika QueueItem akhirnya diproses.

Jangan membuat `QueueWorker` mengetahui implementasi engine.

---

# 7. TTS SERVICE

Sesuaikan `TTSService` agar dapat memilih engine berdasarkan request/item.

Tetap pertahankan tanggung jawab:

```text
Cache
Generate
Post-process
Return Audio
```

Engine selection boleh dilakukan melalui `TTSEngineManager`.

Jangan memindahkan logic Queue ke TTSService.

---

# 8. CACHE

**JANGAN mengubah `AudioCache.compute_key()` jika analisis Phase 1 sudah benar.**

Cache sudah memasukkan:

```text
engine
voice
text
speed
pitch
volume
```

Pertahankan behavior tersebut.

Pastikan engine yang dipilih tetap digunakan ketika menghitung cache key.

---

# 9. BACKWARD COMPATIBILITY

Ini adalah persyaratan utama.

V1 harus tetap berjalan:

* konfigurasi lama tetap valid
* request lama tetap valid
* default engine tetap Piper
* voice Piper tetap bekerja
* Queue tetap bekerja
* Worker tetap bekerja
* cache tetap bekerja
* Zone tetap bekerja
* Scheduler tetap bekerja
* Playback tetap bekerja

Jangan mengubah behavior yang tidak diperlukan untuk Multi-Engine.

---

# 10. ERROR HANDLING

Jika request memilih engine yang tidak tersedia, jangan fallback diam-diam ke Piper.

Berikan error yang jelas.

Contoh konsep:

```text
engine_not_found
```

Tetapi ikuti pola exception/error response yang sudah digunakan project V1.

Jangan membuat format error baru jika tidak diperlukan.

---

# 11. TESTING

Tambahkan/update test yang diperlukan untuk membuktikan:

1. Piper tetap dapat digunakan sebagai default.
2. Engine dapat dipilih berdasarkan ID.
3. Engine yang tidak tersedia menghasilkan error.
4. Request tanpa `engine` menggunakan default engine.
5. QueueItem mempertahankan pilihan engine.
6. Cache key tetap membedakan engine.
7. Behavior request V1 tetap kompatibel.

Jangan mengejar refactor besar.

---

# YANG BELUM BOLEH DIBUAT

Phase ini **BUKAN** untuk:

* Voice Registry
* Voice Profile
* Voice Discovery API
* Engine Capability API
* engine TTS kedua
* Edge TTS
* Azure
* ElevenLabs
* Coqui
* Dashboard
* Client UI
* Audio Endpoint
* Emergency Broadcast
* MQTT
* gRPC

Semua itu Phase berikutnya.

---

# ATURAN KETAT

* Gunakan source code aktual sebagai sumber kebenaran.
* Jangan melakukan refactor yang tidak diperlukan.
* Jangan mengubah API yang tidak berkaitan dengan engine selection.
* Jangan menghapus behavior V1.
* Jangan menambahkan dependency kecuali benar-benar diperlukan.
* Jangan mengubah Piper implementation tanpa alasan.
* Jangan membuat abstraction tambahan jika `TTSEngine` + `EngineFactory` + `TTSEngineManager` sudah cukup.
* Jangan memilih atau memasukkan engine kedua.
* Jangan commit.
* Jangan push.

---

# VALIDASI

Setelah implementasi:

1. Jalankan test suite yang relevan.
2. Pastikan test V1 tetap lulus.
3. Pastikan default engine tetap Piper.
4. Pastikan request lama tetap valid.
5. Pastikan request dengan `engine` dapat memilih engine yang tersedia.
6. Pastikan QueueItem membawa engine sampai TTS diproses.
7. Pastikan cache tetap engine-aware.
8. Pastikan tidak ada perubahan behavior yang tidak terkait.

Jika test gagal karena perubahan Phase 2, perbaiki hanya jika masalah memang disebabkan implementasi Phase 2.

---

# OUTPUT

Jangan menampilkan kode panjang.

Berikan ringkasan maksimal 6 poin:

1. perubahan architecture
2. file utama yang berubah
3. mekanisme engine selection
4. backward compatibility
5. test yang dijalankan
6. hasil test

Jangan membuat dokumentasi panjang.

Jangan commit.

Jangan push.

Setelah selesai, **STOP dan tunggu Phase 3.**


# V2 PHASE 3 — PIPER ENGINE REFACTORING & ISOLATION

Lanjutkan dari hasil V2 Phase 2.

Phase 2 telah berhasil memperkenalkan:

```text
TTSService
    ↓
TTSEngineManager
    ↓
TTSEngine
    ↓
PiperEngine
```

Engine dapat dipilih per-request/QueueItem, dengan Piper tetap sebagai default.

Sekarang fokus Phase 3 adalah:

> memastikan Piper menjadi implementation `TTSEngine` yang bersih, terisolasi, dan menjadi reference implementation untuk engine-engine V2 berikutnya.

## TUJUAN

Refactor **hanya jika diperlukan** agar `PiperEngine`:

* sepenuhnya mengikuti kontrak `TTSEngine`
* tidak membocorkan konsep Piper ke layer lain
* mudah digantikan oleh engine lain
* memiliki error handling yang konsisten
* memiliki konfigurasi yang jelas
* tetap kompatibel dengan behavior V1

**Jangan menambahkan engine kedua pada phase ini.**

---

# 1. AUDIT PIPER ENGINE

Periksa implementasi `PiperEngine` aktual setelah Phase 2.

Pastikan semua logic khusus Piper berada di:

```text
tts/piper_engine.py
```

atau module internal Piper yang memang diperlukan.

Layer berikut tidak boleh bergantung pada detail Piper:

```text
TTSService
TTSEngineManager
Queue
Worker
Scheduler
Zone
API
Client
Cache
```

Jangan melakukan refactor besar jika isolasi saat ini sudah cukup baik.

---

# 2. TTSEngine CONTRACT

Pertahankan interface `TTSEngine` yang sudah ada.

Jangan mengubah:

```text
async synthesize(text, voice, speed) -> bytes
```

kecuali ada masalah nyata yang ditemukan dari source code.

Jangan memasukkan:

* Piper-specific argument
* Piper-specific object
* Piper model path
* Piper CLI flag

ke dalam interface generic.

---

# 3. PIPER CONFIGURATION

Audit konfigurasi Piper.

Pastikan konfigurasi khusus Piper tidak bocor ke konfigurasi generic TTS tanpa alasan.

Identifikasi:

* binary path
* models directory
* default voice
* timeout
* retry
* temp directory
* argument Piper
* environment dependency

Jika struktur config saat ini sudah baik, **jangan memindahkannya hanya demi refactor**.

Pertahankan konfigurasi V1 yang sudah ada.

---

# 4. VOICE RESOLUTION

Untuk Phase 3, **JANGAN membuat Voice Registry**.

Piper boleh tetap menggunakan mekanisme V1:

```text
voice ID
    ↓
models/{voice}.onnx
models/{voice}.onnx.json
```

Namun pastikan logic tersebut hanya diketahui oleh Piper.

Layer generic tidak boleh berasumsi bahwa:

```text
voice == filename .onnx
```

Ini penting karena Phase 4 akan memperkenalkan Voice Profile/Voice Registry.

---

# 5. SPEED / AUDIO PARAMETERS

Audit mapping parameter:

```text
speed
pitch
volume
```

Bedakan dengan jelas:

```text
TTSEngine
    ↓
engine-supported parameters

TTSService
    ↓
generic post-processing
```

Piper-specific behavior seperti:

```text
speed → --length_scale
```

harus tetap berada di `PiperEngine`.

Jangan memindahkan Piper-specific logic ke `TTSService`.

Jika Piper tidak mendukung pitch secara native dan V1 melakukan post-processing, pertahankan behavior V1.

Jangan membuat capability system pada phase ini.

---

# 6. PROCESS / TEMP FILE / AUDIO

Audit:

* subprocess execution
* temporary files
* cleanup
* WAV reading
* timeout
* process exit code
* stderr
* binary missing
* model missing
* malformed output
* cancellation

Pastikan resource selalu dibersihkan.

Jangan mengubah behavior yang sudah benar hanya untuk melakukan refactor.

---

# 7. ERROR HANDLING

Pertahankan error hierarchy yang sudah digunakan V1.

Bedakan:

```text
Engine unavailable
Voice unavailable
TTS generation failed
Invalid output
Timeout
Process failure
```

Jangan membuat exception baru jika exception existing sudah sesuai.

Gunakan exception existing seperti:

```text
TTSEngineNotAvailableError
TTSGenerationError
```

sesuai pola project aktual.

Jangan membuat format error API baru.

---

# 8. RETRY

Pertahankan policy retry V1.

Retry hanya untuk error yang memang dianggap transient.

Jangan melakukan retry untuk masalah permanen seperti:

* binary tidak ada
* model tidak ada
* voice tidak valid
* konfigurasi salah

Jika implementasi V1 sudah benar, jangan ubah.

---

# 9. ENGINE FACTORY

Pastikan Piper tetap diregistrasikan melalui `EngineFactory`.

Jangan membuat `TTSEngineManager` mengetahui detail:

```text
PiperEngine(...)
```

Manager harus tetap generic.

Konsep yang diinginkan:

```text
EngineFactory
    ↓
registered builder
    ↓
PiperEngine
```

Bukan:

```text
TTSEngineManager
    ↓
if engine == "piper":
    PiperEngine(...)
```

---

# 10. TESTING

Tambahkan atau perbaiki test khusus Piper jika diperlukan.

Minimal pastikan:

1. Piper memenuhi `TTSEngine`.
2. Piper dapat dibuat melalui `EngineFactory`.
3. Piper dapat dipanggil melalui `TTSEngineManager`.
4. Default Piper tetap bekerja.
5. Voice valid menghasilkan audio.
6. Voice/model tidak ditemukan menghasilkan error yang benar.
7. Binary Piper tidak ditemukan menghasilkan error yang benar.
8. Speed tetap memiliki behavior V1.
9. Temp file/directories dibersihkan.
10. Retry behavior tetap sesuai V1.
11. TTSService tidak perlu mengetahui detail Piper.
12. Test existing V1 tidak rusak.

Jika test suite tidak dapat dijalankan karena dependency/environment, lakukan static/syntax validation dan laporkan secara jujur.

Jangan mengklaim test lulus jika tidak benar-benar dijalankan.

---

# 11. BACKWARD COMPATIBILITY

Wajib mempertahankan:

* konfigurasi V1
* default Piper
* voice Piper
* API V1
* Queue
* Scheduler
* Zone
* Playback
* cache
* retry behavior

Tidak boleh ada perubahan behavior yang tidak berhubungan dengan tujuan Phase 3.

---

# 12. YANG BELUM BOLEH DIBUAT

Jangan implementasikan:

* Voice Registry
* Voice Profile
* Voice Discovery API
* `/tts/voices`
* `/tts/engines`
* Engine Capability
* engine kedua
* Edge TTS
* Azure
* ElevenLabs
* Coqui
* client UI
* Audio Endpoint
* Emergency Broadcast
* MQTT
* gRPC

Semua itu phase berikutnya.

---

# ATURAN KETAT

* Gunakan source code aktual.
* Jangan mengarang behavior.
* Jangan refactor jika tidak diperlukan.
* Jangan mengubah interface generic tanpa alasan kuat.
* Jangan menambah dependency kecuali benar-benar diperlukan.
* Jangan mengubah API publik tanpa alasan.
* Jangan commit.
* Jangan push.

Jika menemukan masalah yang berada di luar scope Phase 3, **catat dan jangan kerjakan**.

---

# VALIDASI AKHIR

Setelah implementasi:

1. Jalankan test yang relevan.
2. Jalankan static/syntax validation.
3. Pastikan Piper tetap menjadi default.
4. Pastikan `TTSEngineManager` tetap generic.
5. Pastikan tidak ada Piper-specific logic di layer generic.
6. Pastikan behavior V1 tetap kompatibel.
7. Periksa diff agar perubahan hanya terkait Phase 3.

---

# OUTPUT

Berikan ringkasan maksimal 6 poin:

1. apa yang diperbaiki
2. isolasi Piper
3. perubahan interface/config jika ada
4. test yang dijalankan
5. hasil validasi
6. hal yang sengaja tidak disentuh karena di luar scope

Jangan tampilkan kode panjang.

Jangan commit.

Jangan push.

Setelah selesai:

**STOP dan tunggu Phase 4.**


Lanjutkan **V2 PHASE 3 — PIPER ENGINE REFACTORING & ISOLATION** dari kondisi terakhir.

Jangan mengulang pekerjaan yang sudah selesai.

Prioritas:

1. selesaikan isolasi Piper dari layer generic
2. pertahankan kontrak `TTSEngine`
3. pastikan EngineFactory/TTSEngineManager tetap generic
4. audit error handling, retry, subprocess, timeout, dan cleanup
5. validasi backward compatibility
6. jalankan test/static validation yang tersedia

Jangan membuat:

* Voice Registry
* Voice Profile
* API voice/engine
* Engine Capability
* engine kedua
* Client
* Audio Endpoint
* Emergency Broadcast

Jangan melakukan refactor di luar scope.

Jangan commit/push.

Setelah selesai, berikan ringkasan maksimal 6 poin dan STOP.
