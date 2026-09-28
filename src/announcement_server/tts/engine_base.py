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

from announcement_server.tts.engine_capability import EngineCapability
from announcement_server.tts.voice_profile import VoiceProfile


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

    async def list_voices(self) -> list[VoiceProfile]:
        """Mengembalikan daftar voice yang tersedia pada engine ini (V2 Phase 4 — Voice Discovery).

        Implementasi DEFAULT (di sini) mengembalikan list kosong dan SENGAJA
        bukan ``@abstractmethod`` — ini agar penambahan kontrak ini pada
        Phase 4 TIDAK memaksa perubahan pada seluruh test-double ``TTSEngine``
        yang sudah ada di banyak file test (yang hanya peduli pada
        ``synthesize()``, bukan voice discovery). Engine sesungguhnya (mis.
        ``PiperEngine``) WAJIB meng-override method ini dengan discovery yang
        nyata (bukan hardcoded) — lihat ``PiperEngine.list_voices()``.

        Implementasi TIDAK BOLEH mengarang/menebak metadata (``language``,
        ``gender``) yang tidak benar-benar diketahui dari sumber datanya.
        """
        return []

    async def get_voice(self, voice_id: str) -> VoiceProfile | None:
        """Mencari satu voice berdasarkan id. Default: cari lewat ``list_voices()``.

        Engine boleh meng-override ini dengan lookup yang lebih efisien
        (mis. langsung cek file tanpa scan direktori penuh) bila diperlukan;
        default di sini cukup untuk mayoritas kasus karena jumlah voice per
        engine biasanya kecil.
        """
        for voice in await self.list_voices():
            if voice.id == voice_id:
                return voice
        return None

    async def initialize(self) -> None:
        """Lifecycle hook (RC2-1): dipanggil TEPAT SEKALI oleh ``TTSEngineManager``
        setelah engine ini dikonstruksi (``__init__``), sebelum dipakai untuk
        sintesis apa pun.

        Default (di sini) tidak melakukan apa-apa, dan SENGAJA bukan
        ``@abstractmethod`` — mengikuti pola yang sama dengan ``list_voices()``
        dan ``get_capability()`` (Phase 4/7): agar penambahan kontrak ini TIDAK
        memaksa perubahan pada seluruh test-double ``TTSEngine`` yang sudah ada.

        Gunakan hook ini (bukan ``__init__``) untuk pekerjaan setup yang
        bersifat ASYNC (mis. engine masa depan yang perlu memuat model machine
        learning ke GPU memory, atau memeriksa ketersediaan resource remote) —
        ``__init__`` Python bersifat sinkron sehingga tidak cocok untuk
        pekerjaan semacam itu. ``PiperEngine``/``EspeakEngine`` saat ini TIDAK
        meng-override ini karena seluruh setup-nya sudah cukup dengan ``__init__``
        sinkron (menyimpan path config saja, tidak ada I/O berat).
        """
        return None

    async def shutdown(self) -> None:
        """Lifecycle hook (RC2-1): dipanggil TEPAT SEKALI oleh ``TTSEngineManager``
        saat aplikasi shutdown (lihat ``main.py`` lifespan).

        Default (di sini) tidak melakukan apa-apa, SENGAJA bukan
        ``@abstractmethod`` (pola yang sama seperti ``initialize()`` di atas).

        Gunakan hook ini untuk melepaskan resource yang benar-benar dipegang
        engine (mis. model di GPU memory, koneksi persisten ke proses lain).
        ``PiperEngine``/``EspeakEngine`` saat ini TIDAK meng-override ini
        karena keduanya tidak pernah memegang resource yang bertahan di
        antara panggilan ``synthesize()`` — subprocess selalu dijalankan,
        ditunggu selesai, dan dibersihkan sepenuhnya di setiap panggilan
        (lihat audit RC1-1/RC1-4), sehingga tidak ada apa pun untuk
        dilepaskan di sini.
        """
        return None

    async def get_capability(self) -> EngineCapability:
        """Mengembalikan kapabilitas engine ini (V2 Phase 7 — Engine Capability, murni informasional).

        Default (di sini) mengembalikan kapabilitas paling konservatif
        (hanya ``supports_speed=True``, sisanya False/None) dan SENGAJA
        bukan ``@abstractmethod`` dengan alasan yang sama seperti
        ``list_voices()`` — agar tidak memaksa perubahan pada seluruh
        test-double ``TTSEngine`` yang sudah ada. Engine sesungguhnya boleh
        meng-override untuk melaporkan kapabilitas native yang SEBENARNYA
        dimiliki (lihat ``PiperEngine``/``EspeakEngine``), TIDAK BOLEH
        mengarang kapabilitas yang sebenarnya tidak dimiliki.
        """
        return EngineCapability()
