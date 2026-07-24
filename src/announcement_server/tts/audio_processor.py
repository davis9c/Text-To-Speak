"""Audio Processor — post-processing volume & pitch pada WAV PCM.

SENGAJA dipisah dari ``TTSEngine`` manapun karena operasi ini generik dan
sama untuk semua engine (Piper sekarang, Edge TTS/Azure/dst nanti) —
menaruhnya di sini menghindari duplikasi logika volume/pitch di setiap
implementasi engine baru.

Hanya memakai modul stdlib (``wave`` + ``audioop``) — sengaja tidak
menambah dependency pihak ketiga yang berat (mis. librosa/pydub) hanya
untuk operasi sederhana ini, sejalan dengan prinsip "tidak membuat
technical debt" / menjaga jejak dependency seminimal mungkin untuk
aplikasi yang harus mudah di-install di Windows sebagai service.
"""

from __future__ import annotations

import io
import logging
import wave

try:
    import audioop
except ImportError:  # pragma: no cover - audioop dihapus dari stdlib mulai Python 3.13 (PEP 594)
    import audioop_lts as audioop  # type: ignore[import-not-found, no-redef]

logger = logging.getLogger(__name__)


class AudioProcessor:
    """Menerapkan penyesuaian volume dan pitch pada audio WAV PCM."""

    def apply_volume(self, wav_bytes: bytes, volume: float) -> bytes:
        """Mengatur volume (gain) audio. ``volume=1.0`` berarti tidak berubah.

        Diimplementasikan lewat penskalaan amplitudo sample (``audioop.mul``)
        — pendekatan standar dan akurat untuk gain control, tanpa efek
        samping pada durasi/pitch.
        """
        if volume == 1.0:
            return wav_bytes

        with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
            params = reader.getparams()
            frames = reader.readframes(reader.getnframes())

        adjusted_frames = audioop.mul(frames, params.sampwidth, volume)
        return self._write_wav(adjusted_frames, params)

    def apply_pitch(self, wav_bytes: bytes, pitch: float) -> bytes:
        """Mengubah pitch audio lewat teknik resampling sederhana. ``pitch=1.0`` berarti tidak berubah.

        KETERBATASAN YANG DISENGAJA: teknik ini (memampatkan/melebarkan
        jumlah sample lalu memutarnya kembali pada frame rate asli) turut
        mengubah durasi/tempo audio sebagai efek samping (pitch naik ->
        audio ikut terdengar lebih cepat, dan sebaliknya) — efek yang sama
        seperti mempercepat/memperlambat rekaman kaset. Pitch-shift yang
        independen terhadap tempo membutuhkan algoritma DSP yang jauh lebih
        berat (phase vocoder, mis. lewat librosa/pyrubberband) yang sengaja
        TIDAK ditambahkan sebagai dependency pada Phase 3 ini. Jika pada
        pemakaian nyata pitch presisi tinggi dibutuhkan, ini adalah
        kandidat item untuk Phase 15 (Future Development).
        """
        if pitch == 1.0:
            return wav_bytes

        with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
            params = reader.getparams()
            frames = reader.readframes(reader.getnframes())

        internal_rate = max(1, round(params.framerate / pitch))
        converted_frames, _ = audioop.ratecv(
            frames,
            params.sampwidth,
            params.nchannels,
            params.framerate,
            internal_rate,
            None,
        )
        new_nframes = len(converted_frames) // (params.sampwidth * params.nchannels)
        # Frame rate pada header WAV TETAP frame rate ASLI (bukan
        # internal_rate) — justru karena diputar pada rate asli inilah
        # jumlah sample yang sudah dimampatkan/dilebarkan menghasilkan efek
        # pitch shift.
        new_params = params._replace(framerate=params.framerate, nframes=new_nframes)
        return self._write_wav(converted_frames, new_params)

    @staticmethod
    def _write_wav(frames: bytes, params: wave._wave_params) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setparams(params)
            writer.writeframes(frames)
        return buffer.getvalue()
