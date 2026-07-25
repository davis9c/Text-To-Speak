# Direktori Sounds (Phase 7 — Announcement Engine)

Simpan file audio statis di sini (bell, alarm, jingle, atau file WAV/MP3
apa pun yang ingin diputar TANPA melalui TTS).

Contoh penempatan file:

```
sounds/
├── bell.wav
├── alarm.mp3
└── jingle.mp3
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
