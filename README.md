# Announcement Server

Production Ready Text-to-Speech Announcement Server berbasis Python untuk Windows.
Menerima request HTTP, mengantrekan pengumuman, mengubah teks menjadi suara
(offline, multi-engine), memutar audio ke sistem TOA, serta mendukung Public
Address (PA) multi-zona.

> **Version:** 2.0.0 — Multi-Engine TTS Platform. Arsitektur TTS generic lewat `TTSEngine`/`TTSEngineManager`/`EngineFactory`, mendukung lebih dari satu engine sekaligus: **Piper** (default), **eSpeak NG** (opsional), dan **StyleTTS2** (opsional, neural/voice-cloning) — lengkap dengan Voice Registry & Engine Capability discovery (`GET /tts/engines`, `GET /tts/voices`). Seluruh fitur inti tetap berjalan tanpa perubahan — lihat [Multi-Engine TTS (V2)](#multi-engine-tts-v2) dan [Migration Guide (V1 → V2)](#migration-guide-v1--v2).

## Requirements

- Python 3.11+
- Windows 10/11 (development/production) — kompatibel juga di Linux/macOS untuk development.
- **Piper TTS** (engine TTS default) — lihat bagian [Setup Piper (TTS Engine)](#setup-piper-tts-engine) di bawah.
- **eSpeak NG** (opsional, engine TTS kedua sejak V2) — lihat [Setup eSpeak NG (Opsional)](#setup-espeak-ng-engine-tts-kedua-opsional) di bawah. Server tetap berjalan normal dengan Piper saja jika eSpeak NG tidak dipasang.
- **StyleTTS2** (opsional, engine TTS ketiga sejak V2, neural/voice-cloning berbasis PyTorch) — lihat [Setup StyleTTS2 (Opsional)](#setup-styletts2-engine-tts-ketiga-opsional) di bawah. Jauh lebih berat dari Piper/eSpeak NG (butuh `torch`); server tetap berjalan normal tanpanya.
- **ffmpeg** (opsional) — hanya dibutuhkan untuk memutar file audio statis berformat SELAIN `.wav` (mis. MP3). Lihat [Setup ffmpeg (opsional, Announcement Engine)](#setup-ffmpeg-opsional-announcement-engine) di bawah.

## Setup Piper (TTS Engine)

Server ini memakai [Piper](https://github.com/rhasspy/piper) sebagai engine TTS offline default. Piper **tidak disertakan** dalam repository ini (ukurannya besar & berlisensi terpisah) — unduh secara manual:

1. Unduh binary Piper untuk Windows dari [rilis resmi Piper](https://github.com/rhasspy/piper/releases) (pilih `piper_windows_amd64.zip` atau setara).
2. Ekstrak sehingga `piper.exe` berada di `engines/piper/piper.exe` (relatif terhadap root project), atau sesuaikan path lewat `tts.piper_binary_path` di `config/config.yaml`.
3. Unduh minimal satu voice model (mis. `en_US-lessac-medium`) dari [halaman voices Piper](https://github.com/rhasspy/piper/blob/master/VOICES.md) — setiap voice terdiri dari 2 file: `<voice>.onnx` dan `<voice>.onnx.json`.
4. Taruh keduanya di `engines/piper/models/`, atau sesuaikan lewat `tts.piper_models_dir`.
5. Set `tts.default_voice` di `config/config.yaml` sesuai nama voice yang diunduh (tanpa ekstensi).

> Jika Piper belum ter-setup, server tetap bisa berjalan normal (endpoint `/health`, `/queue`, dll tetap berfungsi) — hanya item yang dikirim lewat `POST /speak` yang akan berstatus `failed` saat diproses, dengan `error_message` yang menjelaskan penyebabnya. Ini disengaja (graceful degradation) agar satu komponen yang belum siap tidak menjatuhkan seluruh server.

## Setup eSpeak NG (Engine TTS Kedua, Opsional)

Sejak **V2**, server mendukung lebih dari satu TTS engine sekaligus. [eSpeak NG](https://github.com/espeak-ng/espeak-ng) tersedia sebagai engine kedua (open source, GPL-3.0, offline) — **opsional**, Piper tetap default dan cukup dipakai sendirian jika tidak butuh eSpeak NG.

1. Unduh & pasang eSpeak NG untuk Windows dari [rilis resmi eSpeak NG](https://github.com/espeak-ng/espeak-ng/releases) (installer `.msi`), atau via package manager di Linux/macOS (mis. `apt install espeak-ng`, `brew install espeak-ng`).
2. Pastikan binary `espeak-ng` dapat diakses lewat PATH sistem, atau set path absolut lewat `tts.espeak_binary_path` di `config/config.yaml`.
3. Aktifkan eSpeak NG sebagai engine tambahan (berdampingan dengan Piper) lewat `tts.additional_engines`:

 ```yaml
 tts:
 engine: piper # tetap default, TIDAK berubah
 additional_engines:
 - espeak # engine tambahan, opsional
 espeak_binary_path: espeak-ng
 ```

4. Voice eSpeak NG TIDAK perlu diunduh terpisah (berbeda dari Piper) — seluruh voice sudah bawaan instalasi, otomatis terdeteksi lewat `GET /tts/voices/espeak` (lihat [Multi-Engine TTS (V2)](#multi-engine-tts-v2)).

> Jika `tts.additional_engines` dikosongkan (default), perilaku server 100% identik dengan V1 — hanya Piper yang aktif. Jika eSpeak NG diaktifkan tapi binary-nya tidak ditemukan, server tetap start normal (graceful degradation, sama seperti Piper) — hanya request yang secara eksplisit memilih `"engine": "espeak"` yang akan gagal dengan pesan error jelas.

## Setup StyleTTS2 (Engine TTS Ketiga, Opsional)

[StyleTTS2](https://github.com/yl4579/StyleTTS2) adalah engine TTS neural berbasis PyTorch (voice cloning dari referensi audio via style diffusion) — **jauh lebih berat** dibanding Piper/eSpeak NG (butuh checkpoint model + dependency Python seperti `torch`), dan **sepenuhnya opsional**.

1. Siapkan dependency Python StyleTTS2 (`torch`, `styletts2`, dst) di environment Python server — **SENGAJA tidak** dimasukkan ke `requirements.txt` project ini (berat, opsional; menambahkannya sebagai wajib akan memaksa seluruh deployment — termasuk yang hanya butuh Piper — mengunduh PyTorch). Instal terpisah sesuai kebutuhan.
2. Siapkan checkpoint model (`model.pth`) dan file config (`config.yml`) StyleTTS2, taruh sesuai `tts.styletts2_checkpoint_path`/`tts.styletts2_config_path` (default: `engines/styletts2/model.pth` dan `engines/styletts2/config.yml`).
3. Siapkan katalog voice: kumpulan file audio referensi `.wav` di direktori `tts.styletts2_voices_dir` (default: `engines/styletts2/voices/`) — **satu file `.wav` = satu voice**, nama file (tanpa ekstensi) menjadi voice ID. Berbeda dari Piper (butuh voice model terpisah per-suara) dan eSpeak NG (voice bawaan binary) — StyleTTS2 melakukan voice cloning dari referensi audio yang Anda sediakan sendiri.
4. Aktifkan lewat `tts.additional_engines`:

 ```yaml
 tts:
 engine: piper # tetap default, TIDAK berubah
 additional_engines:
 - styletts2 # engine tambahan, opsional
 styletts2_checkpoint_path: "engines/styletts2/model.pth"
 styletts2_config_path: "engines/styletts2/config.yml"
 styletts2_voices_dir: "engines/styletts2/voices"
 styletts2_diffusion_steps: 5 # trade-off kualitas vs latensi sintesis
 ```

> Sama seperti eSpeak NG: jika dependency/checkpoint StyleTTS2 tidak tersedia, server tetap start normal (graceful degradation) — hanya request dengan `"engine": "styletts2"` yang akan gagal dengan pesan error jelas. Parameter style StyleTTS2 lain (`alpha`, `beta`, `embedding_scale`) memakai nilai default tetap (mengikuti default resmi StyleTTS2) dan **tidak dapat dikontrol per-request** — hanya `diffusion_steps` yang dieksposisikan lewat config karena berdampak langsung pada latensi sintesis. Model dimuat **lazy** (baru dimuat ke memory saat request pertama ke StyleTTS2 diproses, bukan saat server startup) agar startup server tidak terhambat oleh loading model yang berat.

## Setup ffmpeg (opsional, Announcement Engine)

Server dapat memutar file audio statis (bell/alarm/jingle) lewat `POST /speak` dengan `{"type": "audio", "file": "..."}` (lihat [Endpoint Queue System](#endpoint-queue-system-tts-dan-announcement-engine) di bawah). File berformat `.wav` diputar LANGSUNG tanpa dependensi tambahan apa pun. **ffmpeg hanya dibutuhkan untuk format lain (mis. MP3)** — dipakai untuk mengonversi file tsb ke WAV secara otomatis.

1. Unduh ffmpeg untuk Windows dari [rilis resmi ffmpeg (gyan.dev builds)](https://www.gyan.dev/ffmpeg/builds/) atau [ffmpeg.org](https://ffmpeg.org/download.html).
2. Ekstrak lalu tambahkan folder `bin/` (berisi `ffmpeg.exe`) ke PATH sistem, ATAU set path absolut lewat `announcement.ffmpeg_binary_path` di `config/config.yaml`.
3. Simpan file audio (bell/alarm/jingle/dll) di direktori `sounds/` (lihat `announcement.sounds_dir`).

> Jika ffmpeg belum ter-setup, server tetap berjalan normal — file `.wav` tetap bisa diputar tanpa masalah. Hanya item bertipe `audio` dengan sumber SELAIN `.wav` yang akan berstatus `failed` saat diproses (`error_message` menjelaskan bahwa ffmpeg tidak ditemukan). Konsisten dengan prinsip graceful degradation yang sama seperti Piper di atas.

## Windows Service

Jalankan sebagai Windows Service (auto-start saat boot, auto-restart jika crash) lewat NSSM:

1. Unduh NSSM dari https://nssm.cc/download, salin `nssm.exe` ke `tools\nssm\nssm.exe` (lihat `tools/nssm/README.md`).
2. **Run as Administrator**: `install_service.bat` — membuat venv, install dependencies, install & start service `AnnouncementServer` (auto-start Windows aktif).
3. `restart_service.bat` — restart service (mis. setelah ubah `config/config.yaml`).
4. `uninstall_service.bat` — stop & hapus service (venv/config tidak dihapus).

Cek status: `sc query AnnouncementServer`. Log proses service: `logs\service_stdout.log` / `logs\service_stderr.log` (terpisah dari log aplikasi di `logs\announcement_server.log`).

## Instalasi & Menjalankan (Windows)

```bat
run.bat
```

Script ini akan otomatis:
1. Membuat virtual environment (`venv/`) jika belum ada.
2. Menginstall dependencies dari `requirements.txt`.
3. Menjalankan server di `http://0.0.0.0:8000`.

## Instalasi & Menjalankan (manual / Linux / macOS, untuk development)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)/src
uvicorn announcement_server.main:app --reload
```

## Dokumentasi API

Setelah server berjalan:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI schema: <http://localhost:8000/openapi.json>

## Endpoint Queue System, TTS, dan Announcement Engine

| Method | Path | Deskripsi |
|--------|-------------------|-------------------------------------------------------|
| POST | `/speak` | Menambahkan pengumuman baru ke antrean (TTS atau file audio statis, lihat `type`) |
| GET | `/queue` | Melihat antrean (default: item aktif — pending/processing) |
| DELETE | `/queue/{item_id}`| Membatalkan item PENDING |
| POST | `/clear` | Membatalkan seluruh item PENDING |

`POST /speak` mendukung DUA sumber audio lewat field `type`:

Contoh `type="tts"` (default):

```json
{
 "type": "tts",
 "text": "Nomor antrean A001, silakan menuju loket 3.",
 "priority": "normal",
 "engine": null,
 "voice": null,
 "speed": 1.0,
 "pitch": 1.0,
 "volume": 1.0
}
```

Contoh `type="audio"` (memutar file statis — bell/alarm/jingle/MP3/WAV apa pun):

```json
{
 "type": "audio",
 "file": "sounds/bell.mp3",
 "priority": "high"
}
```

- `type`: `tts` (default) | `audio`.
- `text`: WAJIB diisi (tidak boleh kosong) jika `type="tts"`. Untuk `type="audio"`, bersifat opsional — jika dikosongkan, otomatis diisi `"[audio] <file>"` supaya `GET /queue` tetap informatif.
- `file`: WAJIB diisi jika `type="audio"` — path RELATIF terhadap `announcement.sounds_dir` (default `sounds/`), mis. `"bell.mp3"` atau `"alarms/fire.wav"`. Path yang mencoba keluar dari direktori ini (mis. `"../../secret.txt"`) ditolak.
- `priority`: `urgent` | `high` | `normal` (default) | `low`.
- `voice`/`speed`/`pitch`: hanya relevan untuk `type="tts"` — diabaikan untuk `type="audio"`. Lihat penjelasan masing-masing di bawah.
- `engine` (**V2**): nama TTS engine, mis. `"piper"` atau `"espeak"`. Kosongkan (`null`) untuk memakai engine default server (`tts.engine`, perilaku V1 tidak berubah). Engine yang tidak dikenal/tidak aktif menghasilkan error `503` yang jelas — TIDAK ADA fallback diam-diam ke engine lain. Lihat [Multi-Engine TTS (V2)](#multi-engine-tts-v2) untuk cara melihat engine & voice yang tersedia.
- `voice`: nama voice yang dipakai — namespace-nya SPESIFIK per-`engine` (mis. Piper: `en_US-lessac-medium`, eSpeak NG: `en-us`). Kosongkan (`null`) untuk memakai `tts.default_voice` dari config (default ini berupa voice Piper — jika memilih `engine="espeak"`, sebaiknya SELALU kirim `voice` eksplisit, lihat catatan di [Multi-Engine TTS (V2)](#multi-engine-tts-v2)).
- `speed`: 0.5–2.0 (1.0 = normal). Dipetakan ke parameter native Piper `--length_scale`.
- `pitch`: 0.5–2.0 (1.0 = normal). **Catatan:** memakai teknik resampling sederhana yang turut memengaruhi tempo/durasi audio (lihat docstring `AudioProcessor.apply_pitch` untuk detail keterbatasan).
- `volume`: 0.0–2.0 (1.0 = normal). Berlaku untuk `type="tts"` maupun `type="audio"` (diterapkan ke audio saat sintesis TTS; untuk file statis, konversi ffmpeg TIDAK mengubah volume file asli — gunakan volume per-zone untuk itu).

Response (`201 Created`) — termasuk field `type`/`file`:

```json
{
 "id": "a1b2c3d4-...",
 "type": "tts",
 "text": "Nomor antrean A001, silakan menuju loket 3.",
 "file": null,
 "priority": "normal",
 "status": "pending",
 "created_at": "2026-07-22T10:00:00Z",
 "updated_at": "2026-07-22T10:00:00Z",
 "error_message": null,
 "voice": "en_US-lessac-medium",
 "speed": 1.0,
 "pitch": 1.0,
 "volume": 1.0,
 "audio_file_path": null,
 "cache_hit": null,
 "position": 1
}
```

> ⚠️ **Penting — seluruh pipeline (Cache/Generate + Playback) terjadi ASINKRON, untuk `type="tts"` MAUPUN `type="audio"`.** Response `201` di atas hanya berarti item berhasil masuk antrean, BUKAN berarti audio sudah jadi/diputar (`audio_file_path` masih `null`). QueueWorker memproses item di background lewat Worker Pipeline; pantau progres lewat `GET /queue?status=completed` (audio sudah jadi DAN — jika sistem audio tersedia — sudah selesai diputar, `audio_file_path` terisi) atau `GET /queue?status=failed` (lihat `error_message` — untuk `type="tts"` mis. voice tidak ditemukan/Piper belum ter-setup; untuk `type="audio"` mis. file tidak ditemukan atau `ffmpeg` belum ter-setup untuk format non-WAV — kegagalan playback TIDAK membuat item `failed`, lihat [Worker Pipeline](#worker-pipeline)).
>
> Audio hasil TTS disimpan sebagai file `.wav` di `tts.cache_dir` (default `cache/audio/`), dengan nama file = SHA256 dari kombinasi `engine + voice + text + speed + pitch + volume`. Mengirim teks yang sama persis dengan parameter sama akan langsung memakai cache (`cache_hit: true`) tanpa memanggil Piper ulang. Untuk `type="audio"`, file `.wav` diputar langsung (`cache_hit: true`, tanpa konversi), sedangkan format lain dikonversi ke WAV oleh `ffmpeg` dan hasilnya disimpan di `announcement.converted_cache_dir` (default `cache/announcement_audio/`) — lihat [Setup ffmpeg (opsional)](#setup-ffmpeg-opsional-announcement-engine).
>
> Audio (baik dari TTS maupun file statis) **otomatis diputar** ke output device aktif oleh Worker Pipeline setelah tahap Cache/Generate selesai — lihat [Worker Pipeline](#worker-pipeline).

`GET /queue` mendukung query param opsional `status` untuk melihat status
tertentu, termasuk riwayat (`completed`, `failed`, `cancelled`) selama
masih tersimpan di memory (dibatasi `queue.max_history` pada config).

## Multi-Engine TTS (V2)

Sejak V2, server mendukung lebih dari satu TTS engine sekaligus lewat arsitektur generic: `TTSEngine` (kontrak) → `TTSEngineManager` (menahan engine aktif) → `EngineFactory` (registry). Piper tetap **default**; engine tambahan (saat ini: **eSpeak NG** dan **StyleTTS2**) bersifat **opsional & opt-in** lewat `tts.additional_engines` (lihat [Setup eSpeak NG](#setup-espeak-ng-engine-tts-kedua-opsional) dan [Setup StyleTTS2](#setup-styletts2-engine-tts-ketiga-opsional)).

### Endpoint Discovery Engine & Voice

| Method | Path | Deskripsi |
|--------|-------------------------------------|------------------------------------------------------------------|
| GET | `/tts/engines` | Daftar engine yang aktif di server ini + kapabilitas masing-masing |
| GET | `/tts/voices` | Seluruh voice dari SELURUH engine aktif |
| GET | `/tts/voices/{engine}` | Voice milik satu engine tertentu |
| GET | `/tts/voices/{engine}/{voice_id}` | Detail satu voice |

Contoh `GET /tts/engines` (dengan Piper + eSpeak NG + StyleTTS2 aktif — `tts.additional_engines: [espeak, styletts2]`):

```json
{
 "engines": [
 {
 "id": "piper",
 "display_name": "Piper",
 "is_default": true,
 "available": true,
 "capability": {
 "supports_speed": true,
 "supports_native_pitch": false,
 "supports_native_volume": false,
 "supports_ssml": false,
 "offline": true,
 "max_text_length": null,
 "native_sample_rate": null
 }
 },
 {
 "id": "espeak",
 "display_name": "Espeak",
 "is_default": false,
 "available": true,
 "capability": {
 "supports_speed": true,
 "supports_native_pitch": true,
 "supports_native_volume": true,
 "supports_ssml": true,
 "offline": true,
 "max_text_length": null,
 "native_sample_rate": null
 }
 },
 {
 "id": "styletts2",
 "display_name": "Styletts2",
 "is_default": false,
 "available": true,
 "capability": {
 "supports_speed": false,
 "supports_native_pitch": false,
 "supports_native_volume": false,
 "supports_ssml": false,
 "offline": true,
 "max_text_length": null,
 "native_sample_rate": 24000
 }
 }
 ],
 "default_engine": "piper"
}
```

> `capability` murni informasional — mendeskripsikan kapabilitas NATIVE engine tsb, TIDAK mengubah pipeline sintesis (`speed` tetap satu-satunya parameter yang diteruskan ke engine; `pitch`/`volume` selalu diterapkan lewat post-processing generic yang sama untuk SEMUA engine, terlepas dari nilai `supports_native_pitch`/`supports_native_volume`). Perhatikan StyleTTS2: `supports_speed=false` (tidak seperti Piper/eSpeak NG) karena parameter `speed` pada kontrak `synthesize()` memang diabaikan oleh engine ini — dikirim tetap valid, hanya tidak berefek.
>
> `available` mencerminkan bahwa engine berhasil diinisialisasi di `TTSEngineManager` saat startup — BUKAN pengecekan real-time apakah binary/dependency-nya masih ada sekarang (lihat [Known Limitations & Future Development](#known-limitations--future-development) — kegagalan sesungguhnya baru terlihat saat item benar-benar disintesis dan berstatus `failed`).

### Memilih Engine & Voice per Request

Kirim field `engine` (opsional) pada `POST /speak`, `POST /zones/{name}/speak`, atau payload `announcement` pada `POST /scheduler`:

```json
{
 "text": "Selamat datang di lobby.",
 "engine": "espeak",
 "voice": "en-us"
}
```

- Voice ID **spesifik per-engine** — voice Piper (`en_US-lessac-medium`), eSpeak NG (`en-us`), dan StyleTTS2 (nama file referensi, mis. `narrator_calm`) berada di namespace terpisah, tidak bisa dipertukarkan antar-engine. Cek `GET /tts/voices/{engine}` untuk voice yang valid pada engine tsb.
- Engine yang tidak dikenal/tidak aktif menghasilkan `503` (`TTSEngineNotAvailableError`) — bukan fallback diam-diam.
- Request TANPA `engine` (payload V1 lama) tetap memakai engine default (Piper) — tidak ada perubahan behavior.

### Lifecycle Engine

Setiap `TTSEngine` (termasuk StyleTTS2) mengikuti kontrak lifecycle berikut:

- **Konstruksi** (`__init__`): dijalankan sinkron sekali oleh `TTSEngineManager` saat startup — HARUS murah (menyimpan config saja), tidak boleh melakukan I/O berat. Piper/eSpeak NG/StyleTTS2 seluruhnya mengikuti ini.
- **`initialize()`** (async, opsional di-override): hook untuk setup async yang berat (mis. memuat model ML ke memory/GPU). Piper/eSpeak NG memakai default no-op (tidak butuh). StyleTTS2 meng-override untuk memuat model secara eager jika dipanggil.
- **`synthesize()`**: dipanggil berulang untuk tiap request. Untuk StyleTTS2, model dimuat **lazy** pada panggilan pertama (bukan saat `__init__`) jika `initialize()` belum pernah dipanggil, lalu dipakai ulang (memoized) untuk panggilan berikutnya.
- **`shutdown()`** (async, opsional di-override): hook untuk melepas resource. Piper/eSpeak NG memakai default no-op (tidak pernah memegang resource yang bertahan). StyleTTS2 meng-override untuk melepas referensi model dari memory.

> **Catatan status saat ini**: `initialize()`/`shutdown()` sudah menjadi bagian dari kontrak `TTSEngine`, tapi **belum dipanggil** oleh `TTSEngineManager`/`main.py` di versi ini (model StyleTTS2 sepenuhnya mengandalkan lazy-loading via `synthesize()`). Wiring eksplisit ke siklus startup/shutdown server adalah kandidat pekerjaan lanjutan, bukan kebutuhan yang sudah terbukti wajib — lihat [Known Limitations & Future Development](#known-limitations--future-development).

### Cara Menambah Engine Baru

Menambah engine TTS baru **tidak memerlukan perubahan** pada `TTSService`, `Queue`, `Scheduler`, `Playback`, `Cache`, REST API, `VoiceRegistry`, maupun `TTSEngineManager` — seluruhnya sudah generic (dibuktikan langsung lewat penambahan eSpeak NG dan StyleTTS2, dua engine dengan karakteristik sangat berbeda, tanpa mengubah satu pun file di layer tersebut). Langkah minimal:

1. Buat class baru di `tts/<nama_engine>_engine.py` yang mewarisi `TTSEngine` (`tts/engine_base.py`), implementasikan `async synthesize(*, text, voice, speed) -> bytes`. Opsional: `list_voices()`, `get_voice()`, `get_capability()`, `initialize()`, `shutdown()` (seluruhnya punya default non-breaking jika tidak di-override).
2. Daftarkan lewat `EngineFactory.register("nama_engine", NamaEngineClass)` di `tts/engine_factory.py`.
3. Tambahkan konfigurasi spesifik-engine (jika perlu) sebagai field baru di `TTSConfig` (`core/config.py`), mengikuti pola `piper_*`/`espeak_*`/`styletts2_*` yang sudah ada.
4. Aktifkan lewat `tts.engine` (sebagai default) atau `tts.additional_engines` (berdampingan dengan default) di `config.yaml`.
5. Jika engine punya dependency Python berat (seperti StyleTTS2 dengan `torch`), **import dependency tersebut secara lokal di dalam method**, bukan di level modul — agar server tetap bisa start tanpa dependency itu terinstall jika engine tidak diaktifkan (lihat `tts/styletts2_engine.py` sebagai contoh).

## Endpoint Audio Playback

| Method | Path | Deskripsi |
|--------|------------|--------------------------------------------------------|
| GET | `/devices` | Melihat daftar output audio device yang tersedia |
| POST | `/device` | Memilih output device aktif untuk playback |
| POST | `/pause` | Menjeda playback yang sedang berjalan |
| POST | `/resume` | Melanjutkan playback yang dijeda |
| POST | `/stop` | Menghentikan playback sepenuhnya (idempotent) |

> ⚠️ **Endpoint di sini murni kontrol manual** (pilih device, pause, resume,
> stop) — belum ada endpoint HTTP untuk "memutar file X" secara langsung
> Penyambungan hasil TTS ke
> playback terjadi **otomatis di background** lewat Worker Pipeline untuk
> setiap item `POST /speak` — lihat [Worker Pipeline](#worker-pipeline)
> di bawah. Endpoint `/pause`, `/resume`, `/stop` di atas tetap berguna
> untuk mengontrol playback yang SEDANG berjalan lewat pipeline tsb (mis.
> menghentikan paksa pengumuman yang salah).
>
> Untuk memutar satu file WAV secara manual di luar pipeline (mis. uji
> coba device baru), gunakan script bantu manual (lihat bagian
> "Verifikasi Playback Manual" di bawah).

Contoh `GET /devices` response:
```json
{
 "devices": [
 {"id": 0, "name": "Speaker (Realtek Audio)", "max_output_channels": 2, "default_samplerate": 44100.0, "is_default": true},
 {"id": 3, "name": "Speaker TOA (USB Audio)", "max_output_channels": 2, "default_samplerate": 48000.0, "is_default": false}
 ],
 "count": 2
}
```

Contoh `POST /device`:
```json
{ "device_id": 3 }
```

Response `/pause`, `/resume`, `/stop`, dan `/device` semuanya memakai format yang sama:
```json
{
 "state": "playing",
 "current_file": "cache\\audio\\7f4f14e...wav",
 "selected_device_id": 3
}
```

`state` bernilai salah satu dari: `idle` (tidak ada playback), `playing`, `paused`.

> Jika PortAudio/driver audio tidak terdeteksi di server (mis. dijalankan di mesin tanpa sound card), endpoint `/health`, `/queue`, `/speak` **tetap berfungsi normal** — hanya endpoint di atas yang akan mengembalikan error `502 PLAYBACK_DEVICE_ERROR` yang jelas, bukan membuat seluruh server gagal start (graceful degradation, sama seperti perilaku Piper).

## Verifikasi Playback Manual

Karena belum ada endpoint "play" (lihat catatan di atas), gunakan script bantu berikut untuk benar-benar mendengar hasilnya di Windows:

```powershell
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "$PWD\src"
python scripts\manual_test_playback.py "cache\audio\<nama_file_hasil_tts>.wav"
```

Script ini akan memutar file, menampilkan daftar output device yang terdeteksi, dan menerima perintah `p` (pause) / `r` (resume) / `s` (stop) / `q` (keluar) langsung dari terminal. Ini murni alat bantu verifikasi lokal, bukan bagian dari server/API.

## Worker Pipeline

`QueueWorker` menjalankan
`AnnouncementPipelineProcessor` sebagai `item_processor`-nya, yang
menyatukan seluruh tahap berikut untuk **setiap** item `POST /speak`
secara otomatis, satu per satu, sesuai priority antrean:

```
Queue → Cache → Generate → Playback → Delay → Queue Berikutnya
```

1. **Queue** — item PENDING di-dequeue.
2. **Cache / Generate** — teks disintesis jadi audio lewat `TTSService`
: cache hit langsung dipakai, cache miss memanggil engine TTS yang dipilih.
3. **Playback** — file WAV hasil sintesis diputar ke output device aktif
 worker menunggu sampai audio **benar-benar selesai
 terdengar** sebelum lanjut.
4. **Delay** — jeda `playback.post_playback_delay_seconds` (default `0.5`
 detik) di `config/config.yaml`, agar antar-pengumuman TOA tidak
 bertabrakan/terlalu rapat. Set `0` untuk menonaktifkan jeda.
5. **Queue Berikutnya** — worker otomatis lanjut ke item PENDING
 berikutnya (priority tertinggi dulu, lalu FIFO).

Pantau progres tiap tahap lewat `GET /queue/{item_id}` atau
`GET /queue?status=...` — `status` item baru menjadi `completed` **setelah
seluruh pipeline** (termasuk playback + delay) selesai, bukan lagi hanya
setelah TTS selesai.

> **Playback bersifat best-effort, tidak bisa membuat item gagal.** Jika
> sistem audio tidak tersedia (`playback_manager` `None`, lihat catatan
> graceful degradation di atas) atau playback gagal karena alasan
> device/file, tahap Playback dilewati/dicatat sebagai warning di log —
> item tetap `completed` selama tahap TTS-nya sendiri berhasil. Hanya
> kegagalan pada tahap **TTS** (mis. voice tidak ditemukan, Piper belum
> ter-setup) yang membuat item berstatus `failed`.

## Endpoint Multi Zone

Setiap **Zone** adalah jalur audio independen: Queue + Worker + Playback
miliknya sendiri (lihat `src/announcement_server/zones/`). Zone `main`
SELALU ada sejak startup (dibangun dari `queue`/`playback` di
`config.yaml`, opsional di-override lewat `zones.main`) dan **tidak dapat
dihapus** — seluruh endpoint lama (`/speak`, `/queue`, `/clear`,
`/devices`, `/device`, `/pause`, `/resume`, `/stop`) tetap beroperasi di
atas zone ini tanpa perubahan apa pun.

| Method | Path | Deskripsi |
|--------|--------------------------|--------------------------------------------------------------------|
| GET | `/zones` | Melihat daftar seluruh zone + status runtime masing-masing |
| POST | `/zones` | Membuat zone baru (Queue+Worker+Playback independen) |
| PUT | `/zones/{name}` | Memperbarui zone (device/volume/enabled) — pembaruan parsial |
| DELETE | `/zones/{name}` | Menghapus zone (zone `main` dilindungi, `409`) |
| GET | `/zones/{name}/queue` | Melihat antrean milik satu zone (sama seperti `GET /queue`) |
| POST | `/zones/{name}/device` | Memilih output device aktif untuk satu zone (sama seperti `POST /device`) |
| POST | `/zones/{name}/speak` | *(tambahan, lihat catatan di bawah)* Mengirim pengumuman ke satu zone |

> ℹ️ **`POST /zones/{name}/speak` — tambahan di luar 6 endpoint literal
> ROADMAP.md.** Roadmap hanya mendaftarkan endpoint manajemen
> zone, belum endpoint untuk benar-benar *mengirim* pengumuman ke zone
> tertentu — tanpa endpoint ini, zone yang dibuat tidak akan pernah punya
> isi. Endpoint ini memakai ulang `SpeakRequest`/`QueueItemResponse`
> apa adanya, tanpa mengubah `api/v1/queue.py` maupun
> `schemas/queue.py` sama sekali. `POST /speak` (tanpa prefix
> zone) **tidak berubah** dan tetap hanya menyasar zone `main`.

Contoh `POST /zones`:

```json
{
 "name": "lobby",
 "device_id": null,
 "volume": 1.0,
 "enabled": true
}
```

Response (`201 Created`):

```json
{
 "name": "lobby",
 "enabled": true,
 "device_id": null,
 "volume": 1.0,
 "created_at": "2026-07-24T10:00:00Z",
 "updated_at": "2026-07-24T10:00:00Z",
 "worker_running": true,
 "playback_state": "idle",
 "pending_count": 0,
 "processing_count": 0
}
```

Contoh `PUT /zones/lobby` (pembaruan parsial — hanya field yang dikirim yang berubah):

```json
{ "volume": 0.6, "enabled": false }
```

Contoh mengirim pengumuman ke zone tertentu:

```bash
curl -X POST http://localhost:8000/zones/lobby/speak \
 -H "Content-Type: application/json" \
 -d '{"text": "Selamat datang di lobby"}'
```

### Bagaimana Zone volume diterapkan

`volume` pada Zone adalah **gain per-channel** (analog volume knob
amplifier TOA) — **berbeda** dari `volume` pada `POST /speak` (gain per-item yang sudah dipanggang ke dalam file cache TTS). Zone volume
diterapkan **saat playback**, ke salinan sementara audio (bukan ke file
cache asli — cache TTS berbasis SHA256 di-share oleh seluruh zone), lewat
`AudioProcessor.apply_volume` yang sama persis dipakai untuk TTS (tidak
diduplikasi). Salinan sementara ini dibuat di `cache/zone_audio/{nama_zone}/`
dan otomatis dihapus setelah selesai diputar. Zone `main` memakai gain
`1.0` secara default, sehingga tidak mengubah perilaku dasar (file
cache diputar langsung, tanpa salinan sementara).

### Konfigurasi Zone via `config.yaml`

Zone tambahan (selain `main`) juga bisa didefinisikan statis lewat
`config/config.yaml` (dibuat otomatis saat startup) — lihat bagian
`zones:` pada file tersebut. Ini murni kenyamanan; seluruh operasi yang
sama (create/update/delete) tetap bisa dilakukan lewat REST API kapan
saja tanpa restart server.

## Endpoint Scheduler

Memicu pengumuman otomatis berbasis waktu — mendukung **Daily**,
**Weekly**, dan **One Time** (lihat ROADMAP.md, contoh: 07.00 → Bell,
12.00 → Istirahat, 15.00 → Pulang). Scheduler murni "mengetuk" antrean
yang sudah ada (`QueueManager.enqueue()`) pada waktu yang
tepat — tidak ada jalur pemrosesan TTS/audio baru.

| Method | Path | Deskripsi |
|--------|-----------------------------|---------------------------------------------------------------|
| GET | `/scheduler` | Melihat daftar seluruh jadwal |
| POST | `/scheduler` | Membuat jadwal baru |
| GET | `/scheduler/{id}` | Melihat detail satu jadwal |
| PUT | `/scheduler/{id}` | Memperbarui jadwal (pembaruan parsial) |
| DELETE | `/scheduler/{id}` | Menghapus jadwal |
| POST | `/scheduler/{id}/trigger` | Memicu satu jadwal SEGERA (manual, untuk verifikasi) tanpa memengaruhi jadwal otomatis berikutnya |

Contoh `POST /scheduler` (Daily — Bell Masuk):

```json
{
 "name": "Bell Masuk",
 "zone": "main",
 "recurrence": "daily",
 "time_of_day": "07:00",
 "announcement": { "type": "audio", "file": "bell.wav", "priority": "high" }
}
```

Contoh Weekly (Istirahat, Senin-Jumat):

```json
{
 "name": "Istirahat",
 "recurrence": "weekly",
 "time_of_day": "12:00",
 "days_of_week": [0, 1, 2, 3, 4],
 "announcement": { "type": "tts", "text": "Waktunya istirahat siang." }
}
```

Contoh One Time:

```json
{
 "name": "Pengumuman Khusus",
 "recurrence": "once",
 "time_of_day": "09:00",
 "run_date": "2026-08-17",
 "announcement": { "type": "tts", "text": "Selamat memperingati HUT Kemerdekaan." }
}
```

- `recurrence`: `daily` | `weekly` | `once`.
- `time_of_day`: format `"HH:MM"` atau `"HH:MM:SS"` (24 jam).
- `days_of_week`: **wajib** untuk `weekly` — daftar angka `0` (Senin) s.d. `6` (Minggu). Diabaikan untuk recurrence lain.
- `run_date`: **wajib** untuk `once` — format `"YYYY-MM-DD"`. Ditolak (`422`) jika sudah berlalu.
- `announcement`: sama persis dengan body `POST /speak` — mendukung `type="tts"`/`type="audio"`.
- `zone`: nama zone tujuan (default `"main"`, lihat `GET /zones`).

> ⚠️ Jadwal `once` **otomatis dinonaktifkan** (`enabled: false`, `next_run_at: null`) setelah terpicu satu kali — tidak akan pernah terpicu lagi. Jadwal `daily`/`weekly` otomatis menghitung `next_run_at` berikutnya setiap kali terpicu. Kegagalan saat memicu (mis. zone tujuan sudah dihapus, atau file audio tidak ditemukan) di-log dan TIDAK menghentikan scheduler — `next_run_at` tetap dimajukan untuk mencegah retry rapat.

### Zona waktu & presisi

Scheduler memeriksa jadwal jatuh tempo setiap `scheduler.poll_interval_seconds` (default 5 detik) — cukup presisi untuk jadwal berbasis menit. Default `scheduler.timezone: "local"` memakai jam sistem apa adanya (tanpa tzinfo eksplisit), paling sesuai untuk perangkat PA fisik. Isi dengan nama zona IANA eksplisit (mis. `"Asia/Jakarta"`) jika server dan lokasi pengumuman berada di zona waktu berbeda — pastikan paket `tzdata` terpasang (lihat `requirements.txt`), terutama di Windows.

### Konfigurasi Schedule via `config.yaml`

Jadwal juga bisa didefinisikan statis lewat `config/config.yaml` (bagian
`schedules:`, dibuat otomatis saat startup) — lihat contoh
Bell/Istirahat/Pulang yang sudah disediakan (nonaktif secara default,
sama seperti contoh `zones:`). Jadwal statis maupun yang dibuat lewat API
sama-sama diproses oleh `SchedulerManager` yang sama; tidak ada
perbedaan perilaku.

## Endpoint WebSocket

`ws://localhost:8000/ws/status` — status real-time TANPA POLLING. Setelah
terhubung, client menerima satu snapshot awal (status seluruh zone),
lalu setiap event yang terjadi secara push (server-initiated), tanpa
client perlu mengirim apa pun.

Format setiap pesan:

```json
{ "event": "<nama_event>", "timestamp": "2026-07-25T10:00:00+00:00", "data": {... } }
```

Event yang dikirim (sesuai ROADMAP.md):

| Event | Kapan dikirim | Contoh `data` |
|------------------|--------------------------------------------------------------|------------------------------------------------------------|
| `snapshot` | Sekali, tepat setelah koneksi terbuka | `{"zones": [...]}` (sama seperti response `GET /zones`) |
| `queue_changed` | Setiap perubahan status item (enqueue/proses/batal/hapus) | `{"reason": "enqueued", "item_id": "...", "status": "pending", "zone": "main"}` |
| `speaking` | Playback mulai memutar audio | `{"file": "cache/audio/....wav", "zone": "main"}` |
| `idle` | Playback berhenti/selesai (baik alami maupun `stop`) | `{"file": null, "zone": "main"}` |
| `pause` | Playback dijeda | `{"file": "...", "zone": "main"}` |
| `resume` | Playback dilanjutkan | `{"file": "...", "zone": "main"}` |
| `finished` | Satu item selesai diproses (completed ATAU failed) | `{"reason": "completed", "item_id": "...", "zone": "main"}` |

Setiap event (kecuali `snapshot`) memiliki field `zone` — nama zone yang menjadi sumber event tsb, karena `/ws/status` bersifat global
(mem-broadcast SELURUH zone dalam satu koneksi, bukan per-zone).

Contoh memakai `websocat`/browser console:

```js
const ws = new WebSocket("ws://localhost:8000/ws/status");
ws.onmessage = (msg) => console.log(JSON.parse(msg.data));
```

> Broadcast bersifat *best-effort*: kegagalan mengirim ke satu client (mis.
> koneksi sudah putus) tidak memengaruhi client lain maupun proses
> Queue/Playback itu sendiri — client yang bermasalah otomatis dibersihkan
> dari daftar koneksi aktif.

## Endpoint Dashboard

Endpoint read-only untuk monitoring/dashboard eksternal — murni agregasi dari komponen yang sudah ada, tidak ada state baru.

| Method | Path | Deskripsi |
|--------|--------------|----------------------------------------------------------------------|
| GET | `/status` | Snapshot lengkap: Queue/Worker/Device/Zone/Current Audio per zone, statistik cache, jumlah client WebSocket, uptime |
| GET | `/history` | Riwayat item selesai (completed/failed/cancelled) lintas zone, terurut terbaru dulu |
| GET | `/metrics` | Ringkasan angka: jumlah item per status, zone, jadwal aktif, client WebSocket, cache |
| GET | `/health` | Health check ringan untuk watchdog/load balancer |

`GET /history` mendukung query param opsional: `zone` (filter satu zone,
404 jika tidak ada), `status` (default: seluruh status final), `limit`
(default 100, maksimum 1000).

## Konfigurasi

Konfigurasi utama ada di [`config/config.yaml`](config/config.yaml). Semua
nilai dapat di-override lewat environment variable dengan prefix `APP_` dan
separator nested `__`, contoh:

```bash
APP_SERVER__PORT=9000
APP_LOGGING__LEVEL=DEBUG
```

Bagian `tts:` mengatur TTS Engine (**V2**: kini mendukung multi-engine):

| Key | Default | Deskripsi |
|-------------------------------|----------------|-------------------------------------------------------------------------------|
| `tts.engine` | `piper` | Engine default/utama — HARUS terdaftar di `EngineFactory` (`piper`/`espeak`/`styletts2`) |
| `tts.additional_engines` | `[]` | **(V2)** Engine tambahan yang diaktifkan berdampingan dengan default, opsional & opt-in — kosong = perilaku V1 (satu engine aktif) |
| `tts.piper_binary_path` | `engines/piper/piper.exe` | Path executable Piper |
| `tts.piper_models_dir` | `engines/piper/models` | Direktori model voice Piper (`.onnx` + `.onnx.json`) |
| `tts.espeak_binary_path` | `espeak-ng` | **(V2)** Path/nama executable eSpeak NG (dipakai hanya jika `espeak` ada di `additional_engines` atau jadi `tts.engine`) |
| `tts.styletts2_checkpoint_path` | `engines/styletts2/model.pth` | Path checkpoint model StyleTTS2 (dipakai hanya jika `styletts2` aktif) |
| `tts.styletts2_config_path` | `engines/styletts2/config.yml` | Path file config model StyleTTS2, dipasangkan dengan checkpoint di atas |
| `tts.styletts2_voices_dir` | `engines/styletts2/voices` | Direktori katalog voice StyleTTS2 (file `.wav` referensi, 1 file = 1 voice) |
| `tts.styletts2_diffusion_steps` | `5` | Jumlah langkah diffusion sampling StyleTTS2 — trade-off kualitas vs latensi |
| `tts.default_voice` | `en_US-lessac-medium` | Voice fallback jika request tidak mengirim `voice` — namespace Piper; kirim `voice` eksplisit saat memilih `engine` lain |
| `tts.cache_dir` | `cache/audio` | Cache audio hasil sintesis (SHA256 dari `engine+voice+text+speed+pitch+volume`) |

Bagian `announcement:` mengatur Announcement Engine:

| Key | Default | Deskripsi |
|-----------------------------------------|--------------------------------|--------------------------------------------------------------------|
| `announcement.sounds_dir` | `sounds` | Direktori file audio statis (bell/alarm/jingle/dst) |
| `announcement.ffmpeg_binary_path` | `ffmpeg` | Path executable ffmpeg, atau nama binary jika sudah ada di PATH |
| `announcement.converted_cache_dir` | `cache/announcement_audio` | Cache hasil konversi ffmpeg ke WAV |
| `announcement.conversion_timeout_seconds`| `30.0` | Timeout maksimum satu proses konversi ffmpeg |

Bagian `scheduler:` mengatur Scheduler:

| Key | Default | Deskripsi |
|-----------------------------------|-----------|----------------------------------------------------------------------------|
| `scheduler.poll_interval_seconds` | `5.0` | Seberapa sering jadwal jatuh tempo diperiksa |
| `scheduler.timezone` | `local` | `"local"` (jam sistem) atau nama zona IANA eksplisit, mis. `"Asia/Jakarta"` |

## Menjalankan Test

```bash
pip install -r requirements.txt
export PYTHONPATH=$(pwd)/src
pytest -v
```

Test dibagi beberapa lapisan:
- `tests/test_queue_manager.py`, `test_queue_manager_tts_fields.py` — unit test murni `QueueManager` (priority, FIFO, cancel, clear, full, pruning, field & method TTS), tanpa worker/HTTP.
- `tests/test_queue_worker.py` — integrasi `QueueManager` + `QueueWorker` dengan stub processor (murni tidak diubah).
- `tests/test_queue_api.py` — endpoint HTTP end-to-end, dengan `QueueManager` di-override lewat `app.dependency_overrides` agar deterministik.
- `tests/test_audio_processor.py` — unit test DSP volume/pitch (`AudioProcessor`), pakai WAV sintetis.
- `tests/test_audio_cache.py` — unit test cache SHA256 (`AudioCache`): key deterministik, atomic write, hit/miss.
- `tests/test_engine_factory.py` — unit test registry `EngineFactory` (Open/Closed Principle).
- `tests/test_piper_engine.py` — unit test `PiperEngine` memakai *fake piper executable* (tidak butuh binary Piper asli) untuk memvalidasi plumbing subprocess: sukses, voice tidak ditemukan, binary tidak ada, exit code gagal, timeout.
- `tests/test_tts_service.py` — unit test orkestrasi `TTSService` (cache hit/miss, post-processing) memakai `FakeEngine`.
- `tests/test_queue_tts_integration.py` — test integrasi penuh: `QueueManager` + `QueueWorker` (tidak diubah) + `TTSQueueProcessor` + `FakeEngine`.
- `tests/test_audio_device_manager.py` — unit test `AudioDeviceManager` memakai fake `sounddevice` module (tidak butuh hardware audio).
- `tests/test_playback_manager.py` — unit test `PlaybackManager`: play, pause/resume (memverifikasi posisi TIDAK reset), stop (idempotent), auto-stop saat audio habis, ganti device, dan `wait_until_finished()`: menunggu selesai alami, selesai karena `stop()`, langsung return saat IDLE.
- `tests/test_playback_api.py` — endpoint HTTP `/devices`, `/device`, `/pause`, `/resume`, `/stop` end-to-end dengan dependency override.
- `tests/test_pipeline_processor.py` — test `AnnouncementPipelineProcessor`: playback dipanggil & ditunggu, playback dilewati saat `PlaybackManager` `None`, kegagalan playback tidak menggagalkan item, kegagalan tahap TTS tetap `failed`, tahap Delay benar-benar menjeda.
- `tests/test_zone_manager.py` — unit test `ZoneManager`: create/list/get/update/delete zone, zone `main` dilindungi dari penghapusan, toggle `enabled` menghentikan/menjalankan worker, tiap zone punya `QueueManager` independen, `shutdown()` menghentikan seluruh zone.
- `tests/test_zones_api.py` — endpoint HTTP `/zones`, `/zones/{name}`, `/zones/{name}/queue`, `/zones/{name}/device`, `/zones/{name}/speak` end-to-end dengan dependency override (`FakeEngine` + `FakeSoundDevice`, tidak butuh Piper/hardware asli); memverifikasi antar-zone (termasuk `main`) benar-benar terisolasi satu sama lain.
- `tests/test_pipeline_processor_volume_gain.py` — test khusus penambahan `volume_gain` pada `AnnouncementPipelineProcessor`: gain default `1.0` tidak mengubah perilaku sama sekali, gain custom benar-benar men-scale audio yang diputar (dibandingkan lewat `AudioProcessor.apply_volume`) tanpa mengubah file cache asli, gain bisa diubah lewat setter tanpa membuat ulang pipeline, dan kegagalan penerapan gain fallback graceful ke file asli.
- `tests/test_audio_asset_resolver.py` — unit test `AudioAssetResolver` memakai *fake ffmpeg executable* (pola sama seperti `test_piper_engine.py`, tidak butuh ffmpeg asli): file `.wav` diputar langsung tanpa konversi, file nested di sub-folder `sounds_dir`, file tidak ditemukan, path traversal ditolak, konversi MP3 berhasil + di-cache (panggilan kedua tidak memanggil ffmpeg ulang), ffmpeg tidak ditemukan, ffmpeg gagal (exit code), ffmpeg timeout.
- `tests/test_announcement_source_processor.py` — unit test `AnnouncementSourceProcessor`: item `type=tts` di-dispatch ke `TTSQueueProcessor`, item `type=audio` di-dispatch ke `AudioAssetResolver` dan hasilnya tersimpan lewat `QueueManager.update_tts_result()` (bukan ke `TTSQueueProcessor`), item `audio` tanpa `source_file`/dengan file tidak ditemukan melempar error yang sesuai.
- `tests/test_speak_announcement_type_api.py` — dua kelompok test: (1) validasi HTTP `POST /speak` untuk `type`/`file` (backward-compat default `type=tts`, `text`/`file` wajib sesuai `type`, `text` otomatis untuk `type=audio` yang tidak diisi); (2) end-to-end `QueueManager` + `AnnouncementSourceProcessor` + `AnnouncementPipelineProcessor` + `QueueWorker` sungguhan (disusun identik dengan `ZoneManager.create_zone()`) memverifikasi item `audio` benar-benar selesai/gagal diproses, serta item `tts` dan `audio` tetap bisa diproses berdampingan oleh worker yang sama.
- `tests/test_scheduler_models.py` — unit test murni `compute_next_run`/`parse_time_of_day`/`parse_run_date`: daily (selalu ada next run, boundary tepat di waktu jadwal dianggap sudah lewat), weekly (hari yang sama minggu ini/depan tergantung waktu sudah lewat atau belum, daftar hari kosong → `None`), once (masa depan vs sudah lewat vs `run_date` kosong).
- `tests/test_scheduler_manager.py` — unit test `SchedulerManager`: CRUD jadwal, validasi (`weekly` tanpa `days_of_week`, `once` tanpa/dengan `run_date` sudah lewat, `announcement` tidak konsisten dengan `type`), `trigger_now` (tidak memengaruhi `next_run_at` terjadwal, melempar error untuk zone tujuan yang tidak ada), dan background loop SUNGGUHAN (bukan mock) yang benar-benar memicu jadwal `once` secara otomatis lalu menonaktifkannya.
- `tests/test_scheduler_api.py` — endpoint HTTP `/scheduler` end-to-end dengan dependency override (`FakeEngine`, tidak butuh Piper asli), memverifikasi seluruh skenario create/get/update/delete/trigger beserta validasi 422/404.
- `tests/test_connection_manager.py` — unit test `ConnectionManager`: connect/disconnect registry, broadcast ke seluruh client, pembersihan koneksi stale otomatis.
- `tests/test_queue_manager_events.py` — unit test event emission pada `QueueManager`: `queue_changed`/`finished` terkirim dengan payload benar di setiap perubahan status, tidak terkirim untuk item yang sudah dibatalkan/tidak ditemukan, default `noop_event_publisher` tidak mengubah perilaku.
- `tests/test_playback_manager_events.py` — unit test event emission pada `PlaybackManager`: `speaking`/`pause`/`resume`/`idle` terkirim di titik yang benar (termasuk simulasi frame audio habis secara alami lewat callback native, bukan hanya lewat `stop`).
- `tests/test_websocket_status_api.py` — end-to-end `/ws/status` dengan dependency override: snapshot awal saat koneksi dibuka, broadcast `queue_changed` real-time saat `POST /zones/{name}/speak`/`DELETE /queue/{id}`, banyak client menerima event yang sama, registry koneksi bersih setelah disconnect.

## Struktur Project

```
announcement-server/
├── src/announcement_server/
│ ├── main.py # Application factory (create_app) + entry point
│ ├── core/
│ │ ├── config.py # Pydantic v2 settings (YAML + env override): App, Server, Logging, TTS, Playback, Queue, Announcement, Zones, Scheduler (SchedulerConfig + dict[str, ScheduleDefinition])
│ │ ├── logging.py # Setup logging (rotating file handler)
│ │ ├── exceptions.py # Custom exception hierarchy + global handler (+ Zone*, + Audio*/Announcement*, + Schedule*/InvalidScheduleError)
│ │ └── events.py # Kontrak EventPublisher + noop_event_publisher + nama event (EVENT_*) — dipakai QueueManager/PlaybackManager, diimplementasikan oleh websocket/manager.py
│ ├── api/
│ │ ├── deps.py # Dependency Injection providers (Settings, QueueManager, AudioDeviceManager, PlaybackManager, ZoneManager, SchedulerManager)
│ │ └── v1/
│ │ ├── health.py # Router: GET /health
│ │ ├── queue.py # Router: /speak, /queue, /queue/{id}, /clear (+ type=tts|audio)
│ │ ├── playback.py # Router: /devices, /device, /pause, /resume, /stop
│ │ ├── zones.py # Router: /zones, /zones/{name}, /zones/{name}/queue, /zones/{name}/device, /zones/{name}/speak
│ │ ├── scheduler.py # Router: /scheduler, /scheduler/{id}, /scheduler/{id}/trigger
│ │ ├── tts.py # Router (V2): /tts/engines, /tts/voices, /tts/voices/{engine}, /tts/voices/{engine}/{voice_id} — discovery, tidak menyentuh filesystem/detail engine tertentu
│ │ └── websocket.py # Router: WebSocket /ws/status — snapshot awal + broadcast real-time (reuse _build_zone_response dari zones.py)
│ ├── queueing/ # Domain Queue System (murni tidak terikat FastAPI)
│ │ ├── models.py # QueueItem (+ field TTS + AnnouncementType/source_file), QueuePriority, QueueItemStatus, DEFAULT_ACTIVE_STATUSES (dipakai bersama queue.py & zones.py)
│ │ ├── manager.py # QueueManager (asyncio.PriorityQueue + registry; enqueue + param announcement_type/source_file; emit event via on_event)
│ │ ├── worker.py # QueueWorker (TIDAK diubah)
│ │ ├── tts_processor.py # TTSQueueProcessor — jembatan QueueWorker <-> TTSService, satu instance per zone
│ │ └── pipeline_processor.py # AnnouncementPipelineProcessor — Queue→Cache/Generate→Playback→Delay→Berikutnya + volume_gain per-zone; Stage 2 diisi AnnouncementSourceProcessor (kontrak ItemProcessor identik, kelas ini TIDAK diubah)
│ ├── announcement/ # Domain Announcement Engine (murni tidak terikat FastAPI/Queue)
│ │ ├── asset_resolver.py # AudioAssetResolver — validasi & (jika perlu) konversi file audio statis ke WAV lewat ffmpeg, dengan cache hasil konversi
│ │ └── source_processor.py # AnnouncementSourceProcessor — dispatcher Stage 2 pipeline: TTSQueueProcessor vs AudioAssetResolver berdasarkan item.announcement_type
│ ├── tts/ # Domain TTS Engine (murni tidak terikat FastAPI/Queue; di-share seluruh zone)
│ │ ├── engine_base.py # Interface TTSEngine (Strategy Pattern) — synthesize + list_voices/get_capability (V2, default non-breaking)
│ │ ├── piper_engine.py # Implementasi Piper (subprocess async) — engine default
│ │ ├── espeak_engine.py # (V2) Implementasi eSpeak NG (subprocess async) — engine kedua, opsional
│ │ ├── styletts2_engine.py # Implementasi StyleTTS2 (in-process PyTorch, lazy model load, dependency lokal/opsional) — engine ketiga, opsional
│ │ ├── engine_factory.py # Factory Pattern: nama engine -> instance; build(name, config)/list_registered_names (V2)
│ │ ├── engine_manager.py # (V2) TTSEngineManager — menahan engine aktif (default + tts.additional_engines), lookup by name
│ │ ├── voice_profile.py # (V2) VoiceProfile — representasi voice generic lintas-engine
│ │ ├── voice_registry.py # (V2) VoiceRegistry — agregasi voice dari seluruh engine aktif, dipakai endpoint /tts/voices*
│ │ ├── engine_capability.py # (V2) EngineCapability — kapabilitas native engine, murni informasional
│ │ ├── audio_processor.py # Post-processing volume & pitch (stdlib wave/audioop) — dipakai ulang untuk zone volume gain
│ │ ├── cache.py # AudioCache berbasis SHA256 (key menyertakan `engine`, di-share seluruh zone, TIDAK per-zone)
│ │ ├── service.py # TTSService: orkestrator pilih-engine (V2) -> cache -> engine -> post-processing
│ │ └── models.py # TTSResult
│ ├── playback/ # Domain Audio Playback (dipakai lewat pipeline; satu instance per zone)
│ │ ├── models.py # AudioDevice, PlaybackState
│ │ ├── device_manager.py # AudioDeviceManager (enumerasi & validasi output device, di-share seluruh zone)
│ │ └── manager.py # PlaybackManager (callback-based stream: play/pause/resume/stop/wait_until_finished; emit event via on_event, dijembatani dari thread native PortAudio lewat run_coroutine_threadsafe)
│ ├── zones/ # Domain Multi Zone (murni tidak terikat FastAPI)
│ │ ├── models.py # Zone (metadata: name/enabled/device_id/volume/timestamps), MAIN_ZONE_NAME
│ │ └── manager.py # ZoneManager — orkestrasi create/update/delete/lookup zone, membungkus QueueManager+QueueWorker+PlaybackManager+AnnouncementSourceProcessor+Pipeline per zone; membungkus event_publisher dengan konteks nama zone
│ ├── scheduler/ # Domain Scheduler (murni tidak terikat FastAPI)
│ │ ├── models.py # ScheduleRecurrence, AnnouncementSpec, ScheduleEntry, compute_next_run (fungsi murni), parse_time_of_day/parse_run_date
│ │ └── manager.py # SchedulerManager — registry jadwal (CRUD, pola sama ZoneManager) + background loop yang meng-enqueue lewat QueueManager.enqueue milik zone tujuan (tidak diduplikasi)
│ ├── websocket/ # Domain WebSocket (murni tidak terikat FastAPI kecuali tipe WebSocket)
│ │ └── manager.py # ConnectionManager — registry client WebSocket + broadcast(event_type, data), memenuhi kontrak EventPublisher (core/events.py)
│ └── schemas/
│ ├── health.py # Response schema /health
│ ├── queue.py # Request/response schema Queue + TTS + type/file
│ ├── playback.py # Request/response schema Playback
│ ├── zones.py # Request/response schema Zone — reuse schema queue.py/playback.py untuk sub-endpoint queue/device/speak
│ ├── scheduler.py # Request/response schema Scheduler — reuse SpeakRequest (queue.py) untuk field `announcement`
│ └── tts.py # (V2) Response schema Engine/Voice discovery — EngineInfo/VoiceInfo TIDAK mengekspos path internal
├── config/config.yaml
├── engines/piper/ # (dibuat manual) binary + model Piper — lihat "Setup Piper" di atas
├── sounds/ # (dibuat manual) file audio statis (bell/alarm/jingle/dst) — lihat announcement.sounds_dir
├── cache/audio/ # (dibuat otomatis) cache audio hasil TTS, di-share seluruh zone
├── cache/zone_audio/{nama_zone}/ # (dibuat otomatis) salinan audio sementara ber-gain zone, auto-dihapus setelah diputar
├── cache/announcement_audio/ # (dibuat otomatis) cache hasil konversi ffmpeg (file non-WAV -> WAV) untuk item type=audio
├── scripts/
│ └── manual_test_playback.py # Alat bantu verifikasi playback manual (bukan bagian API)
├── logs/
├── tests/
├── requirements.txt
├── pytest.ini
├── run.bat
└── README.md
```

## Migration Guide (V1 → V2)

V2 dirancang **100% backward-compatible** dengan V1 — tidak ada breaking change:

- Seluruh payload/response V1 tetap valid apa adanya. Field baru (`engine` pada `POST /speak`/`/zones/{name}/speak`/scheduler, `capability` pada `GET /tts/engines`) selalu **opsional** dengan default yang menghasilkan perilaku identik V1.
- `tts.engine` tetap berarti "engine default", tidak berubah — server yang tidak menyentuh config V2 baru (`tts.additional_engines`, `tts.espeak_binary_path`, `tts.styletts2_*`) berjalan identik dengan V1 (hanya Piper aktif).
- Tidak perlu migrasi data — cache, queue, config lama tetap kompatibel.
- Untuk mulai memakai engine tambahan: ikuti [Setup eSpeak NG](#setup-espeak-ng-engine-tts-kedua-opsional) dan/atau [Setup StyleTTS2](#setup-styletts2-engine-tts-ketiga-opsional), tambahkan nama engine yang diinginkan (`espeak`/`styletts2`) ke `tts.additional_engines`, lalu kirim `"engine": "..."` pada request yang diinginkan saja — request lain yang tidak menyebut `engine` tidak terpengaruh sama sekali.
- Menambah engine BARU (di luar 3 engine bawaan) tidak memerlukan perubahan kontrak API/Core sama sekali — lihat [Cara Menambah Engine Baru](#cara-menambah-engine-baru).
- Endpoint V1 (root-level, tanpa prefix: `/speak`, `/queue`, `/devices`, dll) dan endpoint V2 (prefixed: `/zones/*`, `/scheduler/*`, `/tts/*`, `/maintenance/*`) sengaja hidup berdampingan dengan pola URL berbeda — ini permanen, bukan inkonsistensi yang akan "diperbaiki" di rilis mendatang (mengubahnya akan memecah kompatibilitas V1).

## Known Limitations & Future Development

**Keterbatasan yang diketahui** (bukan bug — keputusan desain yang terdokumentasi): `tts.default_voice` belum sadar-engine (fallback voice hanya cocok untuk Piper — selalu kirim `voice` eksplisit saat memilih engine lain); `EngineInfo.available` mencerminkan status inisialisasi saat startup, bukan health-check real-time; `QueueItemResponse.audio_file_path` dan `CacheStatsResponse.directory` mengekspos path server-lokal; hook `initialize()`/`shutdown()` pada `TTSEngine` belum di-wire ke siklus startup/shutdown `TTSEngineManager`/`main.py` (StyleTTS2 saat ini sepenuhnya mengandalkan lazy-loading via `synthesize()` pertama, bukan `initialize()` eksplisit).

**Pengembangan berikutnya** (di luar cakupan rilis ini): HTML Client, Browser/Desktop Player, Remote Audio Endpoint, Emergency Broadcast, MQTT/gRPC, autentikasi & otorisasi.
