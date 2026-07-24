"""Domain Audio Playback (Phase 4).

Berisi ``AudioDeviceManager`` (enumerasi & validasi output device Windows)
dan ``PlaybackManager`` (memutar file WAV ke device terpilih, dengan
kontrol pause/resume/stop).

SENGAJA DIBUAT INDEPENDEN dari Queue System maupun TTS Engine — modul ini
tidak tahu apa-apa soal ``QueueItem`` atau ``TTSService``. Ia hanya tahu
cara memutar sebuah file WAV ke sebuah audio device. Menghubungkan hasil
TTS (Phase 3) secara otomatis ke playback ini adalah tanggung jawab
Phase 5 (Worker pipeline: Queue -> Cache -> Generate -> Playback -> Delay
-> Queue Berikutnya), BUKAN Phase 4.
"""
