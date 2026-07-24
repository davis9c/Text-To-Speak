"""Playback Manager.

Memutar file WAV ke output audio device Windows, dengan kontrol
pause/resume/stop yang bisa dipanggil KAPAN SAJA selagi audio sedang
diputar.

--------------------------------------------------------------------------
Keputusan desain — callback-based stream, BUKAN API blocking sederhana:

``sounddevice`` menyediakan 2 gaya API:
1. Gaya sederhana: ``sd.play(data, samplerate)`` lalu ``sd.wait()`` —
   benar-benar BLOCKING sampai audio selesai diputar.
2. Gaya callback: ``sd.OutputStream(callback=...)`` — PortAudio memanggil
   fungsi callback kita berulang kali dari THREAD-nya SENDIRI untuk minta
   potongan sample berikutnya, sehingga thread pemanggil (kita) TIDAK
   pernah diblokir menunggu audio selesai.

Dipilih gaya #2 (callback) karena server harus tetap responsif menerima
request ``POST /pause``, ``/resume``, ``/stop`` KAPAN SAJA selagi audio
sedang diputar. Dengan gaya #1, thread yang menjalankan playback akan
terkunci total sampai audio selesai — pause/stop di tengah jalan jadi
mustahil dilakukan. Deliverable "Blocking Playback" pada roadmap
terpenuhi di level BAWAH: operasi menulis sample ke sound card memang
tetap bersifat blocking I/O, hanya saja dijalankan di thread milik
PortAudio sendiri (bukan di thread yang melayani HTTP request), persis
seperti pola yang sudah dipakai sejak Phase 3 (subprocess Piper dijalankan
via ``asyncio.to_thread`` agar tidak memblokir event loop).

--------------------------------------------------------------------------
Keputusan desain — dependency injection untuk modul ``sounddevice``:

Sama seperti ``AudioDeviceManager``, parameter ``sd_module`` SENGAJA ada
supaya kelas ini bisa diuji tanpa hardware audio sungguhan.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import wave
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from announcement_server.core.exceptions import (
    AudioFileNotFoundError,
    PlaybackDeviceError,
    PlaybackStateError,
)
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.playback.models import PlaybackState

logger = logging.getLogger(__name__)


class OutputStreamProtocol(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class SoundDeviceModule(Protocol):
    """Kontrak minimal modul ``sounddevice`` yang dipakai PlaybackManager."""

    CallbackStop: type[Exception]

    def OutputStream(self, **kwargs: Any) -> OutputStreamProtocol: ...  # noqa: N802 - nama API sounddevice asli


def _default_sounddevice_module() -> SoundDeviceModule:
    import sounddevice as sd  # import lokal: baru dibutuhkan saat benar-benar dipakai di Windows

    return sd


class PlaybackManager:
    """Mengelola playback audio WAV ke output device, dengan pause/resume/stop."""

    def __init__(self, device_manager: AudioDeviceManager, sd_module: SoundDeviceModule | None = None) -> None:
        self._device_manager = device_manager
        self._sd = sd_module if sd_module is not None else _default_sounddevice_module()

        # `_lock` melindungi seluruh state di bawah ini. WAJIB threading.Lock
        # (BUKAN asyncio.Lock) karena diakses juga dari callback PortAudio
        # yang berjalan di thread native, bukan di event loop asyncio.
        self._lock = threading.Lock()
        self._stream: OutputStreamProtocol | None = None
        self._frames: np.ndarray | None = None
        self._position: int = 0
        self._state: PlaybackState = PlaybackState.IDLE
        self._current_file: str | None = None
        self._selected_device_id: int | None = None

        # `_finished_event` (Phase 5): menandai kapan playback saat ini benar-benar
        # selesai — baik karena habis secara alami (frame habis di `callback`,
        # thread native PortAudio) MAUPUN dihentikan paksa lewat `_stop_stream()`
        # (dipanggil dari `stop()` atau otomatis oleh `play()` berikutnya).
        # WAJIB threading.Event (bukan asyncio.Event) dengan alasan yang sama
        # seperti `_lock` di atas: di-set dari thread native PortAudio, bukan
        # dari event loop asyncio. Kondisi awal IDLE -> "sudah selesai" (set),
        # supaya `wait_until_finished()` yang dipanggil tanpa playback aktif
        # langsung return, bukan menunggu selamanya.
        self._finished_event = threading.Event()
        self._finished_event.set()

    # --- Properti status (read-only, aman dibaca dari mana saja) -----------

    @property
    def state(self) -> PlaybackState:
        with self._lock:
            return self._state

    @property
    def current_file(self) -> str | None:
        with self._lock:
            return self._current_file

    @property
    def selected_device_id(self) -> int | None:
        return self._selected_device_id

    # --- Device selection ----------------------------------------------------

    def select_device(self, device_id: int) -> None:
        """Memilih output device aktif. Melempar AudioDeviceNotFoundError jika id tidak valid."""
        self._device_manager.validate_device_id(device_id)
        self._selected_device_id = device_id
        logger.info("Output device untuk playback dipilih: id=%s", device_id)

    # --- Playback control -----------------------------------------------------

    async def play(self, file_path: str) -> None:
        """Memuat file WAV dan memulai playback dari awal (menghentikan playback sebelumnya jika ada)."""
        path = Path(file_path)
        if not path.is_file():
            raise AudioFileNotFoundError(f"File audio tidak ditemukan: {file_path}")

        frames, channels, samplerate = await asyncio.to_thread(self._load_wav, path)
        await asyncio.to_thread(self._start_stream, frames, channels, samplerate, str(path))
        logger.info("Playback dimulai: file=%s", path)

    def pause(self) -> None:
        """Menjeda playback yang sedang berjalan. Melempar PlaybackStateError jika tidak sedang PLAYING."""
        with self._lock:
            if self._state != PlaybackState.PLAYING:
                raise PlaybackStateError(
                    f"Tidak bisa pause: state saat ini adalah '{self._state.value}', bukan 'playing'.",
                    details={"current_state": self._state.value},
                )
            self._state = PlaybackState.PAUSED
        logger.info("Playback dijeda.")

    def resume(self) -> None:
        """Melanjutkan playback yang dijeda. Melempar PlaybackStateError jika tidak sedang PAUSED."""
        with self._lock:
            if self._state != PlaybackState.PAUSED:
                raise PlaybackStateError(
                    f"Tidak bisa resume: state saat ini adalah '{self._state.value}', bukan 'paused'.",
                    details={"current_state": self._state.value},
                )
            self._state = PlaybackState.PLAYING
        logger.info("Playback dilanjutkan.")

    async def stop(self) -> None:
        """Menghentikan playback sepenuhnya (idempotent — aman dipanggil walau sedang IDLE)."""
        await asyncio.to_thread(self._stop_stream)
        logger.info("Playback dihentikan.")

    async def wait_until_finished(self) -> None:
        """Menunggu hingga playback SAAT INI selesai (Phase 5).

        Selesai berarti: audio habis diputar secara alami, ATAU dihentikan
        via ``stop()``/``play()`` baru. Dipakai oleh pipeline Worker
        (Queue -> Cache -> Generate -> Playback -> Delay -> Queue
        Berikutnya) agar item antrean berikutnya baru mulai diproses
        SETELAH pengumuman saat ini benar-benar selesai terdengar.

        Aman dipanggil walau tidak ada playback aktif (``_finished_event``
        sudah dalam kondisi *set* saat IDLE) — langsung return tanpa
        menunggu. ``asyncio.to_thread`` dipakai supaya event loop TIDAK
        diblokir selama menunggu (sama seperti pola I/O blocking lain di
        kelas ini, mis. ``_load_wav``/``_start_stream``).
        """
        await asyncio.to_thread(self._finished_event.wait)

    # --- Internal --------------------------------------------------------------

    def _start_stream(self, frames: np.ndarray, channels: int, samplerate: int, file_path: str) -> None:
        self._stop_stream()  # pastikan tidak ada stream lain yang masih aktif

        with self._lock:
            self._frames = frames
            self._position = 0
            self._current_file = file_path
            self._state = PlaybackState.PLAYING
            self._finished_event.clear()

        def callback(outdata: np.ndarray, frame_count: int, time_info: Any, status: Any) -> None:
            if status:
                logger.warning("Status stream audio tidak normal: %s", status)
            with self._lock:
                if self._state != PlaybackState.PLAYING or self._frames is None:
                    outdata.fill(0)  # PAUSED atau IDLE -> kirim silence, JANGAN majukan posisi
                    return
                remaining = len(self._frames) - self._position
                if remaining <= 0:
                    outdata.fill(0)
                    self._state = PlaybackState.IDLE
                    self._finished_event.set()
                    raise self._sd.CallbackStop
                chunk = min(frame_count, remaining)
                outdata[:chunk] = self._frames[self._position : self._position + chunk]
                if chunk < frame_count:
                    outdata[chunk:].fill(0)
                self._position += chunk

        try:
            stream = self._sd.OutputStream(
                samplerate=samplerate,
                channels=channels,
                dtype="int16",
                device=self._selected_device_id,
                callback=callback,
            )
            stream.start()
        except Exception as exc:  # noqa: BLE001 - bisa berupa PortAudioError atau error driver lain
            with self._lock:
                self._state = PlaybackState.IDLE
                self._frames = None
                self._current_file = None
            raise PlaybackDeviceError(f"Gagal membuka output device untuk playback: {exc}") from exc

        with self._lock:
            self._stream = stream

    def _stop_stream(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._frames = None
            self._position = 0
            self._current_file = None
            self._state = PlaybackState.IDLE
            # Set (bukan clear) di sini: dipanggil dari stop() eksternal atau
            # dari play() berikutnya (lihat _start_stream) — kedua kasus
            # berarti playback SAAT INI sudah selesai/dibatalkan, sehingga
            # siapa pun yang sedang wait_until_finished() harus dilepaskan.
            self._finished_event.set()

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001 - kegagalan cleanup tidak boleh membuat request /stop gagal
                logger.exception("Gagal menghentikan stream audio dengan bersih.")

    @staticmethod
    def _load_wav(path: Path) -> tuple[np.ndarray, int, int]:
        with wave.open(str(path), "rb") as reader:
            channels = reader.getnchannels()
            samplerate = reader.getframerate()
            sampwidth = reader.getsampwidth()
            raw = reader.readframes(reader.getnframes())

        if sampwidth != 2:
            raise PlaybackDeviceError(
                f"Hanya mendukung file WAV 16-bit PCM untuk saat ini (sampwidth={sampwidth} byte).",
            )

        frames = np.frombuffer(raw, dtype=np.int16).reshape(-1, channels)
        return frames, channels, samplerate
