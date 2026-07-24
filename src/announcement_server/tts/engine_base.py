"""TTS Engine Interface.

Semua implementasi engine (Piper sekarang; Edge TTS, Azure, ElevenLabs,
Coqui pada Phase 15 — lihat roadmap) WAJIB mewarisi ``TTSEngine`` ini.
Dengan begitu, ``TTSService`` (pemanggil) tidak pernah bergantung pada
detail implementasi engine tertentu — hanya pada kontrak ini (Dependency
Inversion Principle), dan menambah engine baru tidak memerlukan perubahan
apa pun pada ``TTSService`` maupun ``EngineFactory`` selain registrasi.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TTSEngine(ABC):
    """Kontrak yang harus dipenuhi setiap implementasi TTS engine."""

    @abstractmethod
    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        """Menghasilkan audio dari teks dan mengembalikannya sebagai raw WAV bytes.

        Args:
            text: Teks yang akan diucapkan.
            voice: Identifier voice/model yang dipakai (spesifik per-engine).
            speed: Kecepatan bicara relatif (1.0 = normal).

        Returns:
            Raw bytes berformat WAV (PCM).

        Raises:
            VoiceNotFoundError: Jika voice yang diminta tidak tersedia.
            TTSEngineNotAvailableError: Jika engine tidak bisa dijalankan
                (mis. binary tidak ditemukan).
            TTSGenerationError: Jika proses sintesis gagal atau timeout.

        Catatan desain: ``volume`` dan ``pitch`` SENGAJA tidak menjadi
        parameter interface ini. Keduanya adalah post-processing audio
        generik yang berlaku sama untuk semua engine (lihat
        ``tts.audio_processor.AudioProcessor``), bukan kapabilitas yang
        berbeda-beda per-engine seperti ``voice`` atau ``speed``.
        """
        raise NotImplementedError
