# Direktori Sounds (Phase 7 — Announcement Engine)

Simpan file audio statis di sini (bell, alarm, jingle, atau file WAV/MP3
apa pun yang ingin diputar TANPA melalui TTS).

Contoh penempatan file:

```
sounds/
├── bell.wav
├── alarm.mp3
├── jingle.mp3
└── chime/            # Folder KHUSUS chime (announcement.chime_dir)
    └── chime.wav     # File bernama chime.* / default.* = chime default
```

Lalu panggil lewat `POST /speak` (atau `POST /zones/{name}/speak`):

```json
{
  "type": "audio",
  "file": "sounds/bell.wav"
}
```

Catatan:

- File `.wav` diputar langsung tanpa dependensi tambahan.
- Format lain (mis. `.mp3`) butuh `ffmpeg` terinstall untuk dikonversi ke
  WAV secara otomatis (hasil konversi di-cache, lihat
  `announcement.converted_cache_dir` pada `config/config.yaml`) — lihat
  bagian "Setup ffmpeg" pada README utama project.
- Path pada `file` SELALU relatif terhadap direktori ini
  (`announcement.sounds_dir`) dan tidak dapat keluar darinya (path
  traversal ditolak).

## Chime (efek pembuka pengumuman)

File chime disimpan di folder khusus `sounds/chime/` (dapat diubah lewat
`announcement.chime_dir` pada `config/config.yaml`). Daftar chime yang
tersedia bisa didapatkan lewat `GET /chimes` — dipakai misalnya untuk
dropdown pemilihan chime di dashboard:

```json
{
  "chimes": [
    {"id": "chime", "name": "chime", "file": "chime/chime.wav", "is_default": true}
  ],
  "count": 1,
  "default_chime": "chime/chime.wav"
}
```

Nilai `file` pada response bisa langsung dipakai sebagai field `chime`
pada `POST /speak`. Chime bertanda default (file bernama `chime.*` atau
`default.*`) ditandai `is_default: true` dan dirujuk oleh
`default_chime` pada response.

