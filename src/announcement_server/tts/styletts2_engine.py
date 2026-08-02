"""StyleTTS2 Engine (Phase 12 — engine ketiga, hasil riset Phase 9-11).

Implementasi ``TTSEngine`` berbasis StyleTTS2 (https://github.com/yl4579/StyleTTS2),
model TTS neural berbasis diffusion/style-cloning. Berbeda signifikan dari
``PiperEngine``/``EspeakEngine`` (subprocess CLI ringan) — StyleTTS2 berjalan
IN-PROCESS lewat PyTorch, dengan model yang jauh lebih berat untuk dimuat.

Keputusan desain (lihat Phase 9/10/11 — TIDAK diulang di sini, hanya dirujuk):
  - **Voice** = katalog referensi audio TERKURASI (file ``.wav`` di
    ``styletts2_voices_dir``), persis pola ``PiperEngine`` (scan direktori),
    BUKAN voice-cloning dari upload bebas. ``VoiceProfile.source`` menyimpan
    path file referensi (field generic yang sudah ada, tidak perlu field baru).
  - **Parameter style** (``alpha``/``beta``/``embedding_scale``) memakai
    default tetap yang sama dengan default resmi paket referensi StyleTTS2 —
    TIDAK dieksposisikan per-request (terbukti Phase 10: tidak butuh
    perubahan Core/API). ``diffusion_steps`` SATU-SATUNYA yang dieksposisikan
    lewat config server (dampak langsung ke latensi, bukan sekadar gaya).
  - **speed** (parameter kontrak ``TTSEngine.synthesize()``) diterima tapi
    DIABAIKAN — StyleTTS2 tidak punya kontrol speed pada API inference
    resminya (dikonfirmasi Phase 9 dari dokumentasi resmi, bukan dugaan).
  - **Lifecycle**: model TIDAK dimuat di ``__init__`` (yang berat & sinkron)
    — dimuat LAZY pada ``synthesize()``/``initialize()`` pertama (mana pun
    yang lebih dulu dipanggil), lalu dipakai ulang (memoized). ``shutdown()``
    melepaskan referensi model agar memory/VRAM bisa dibebaskan GC.

Dependency opsional: modul ini SENGAJA tidak meng-import ``styletts2``/
``torch``/``numpy`` di level modul — seluruhnya di-import LOKAL di dalam
method yang membutuhkannya. Ini KRUSIAL: ``EngineFactory`` meng-import modul
ini secara tanpa syarat (sama seperti ``piper_engine``/``espeak_engine``),
sehingga jika import dilakukan di level modul dan package ``styletts2``/
``torch`` belum terinstall, SELURUH APLIKASI (termasuk Piper/eSpeak NG) akan
gagal start. Dengan lazy import, aplikasi tetap berjalan normal tanpa
``styletts2`` terinstall sama sekali — StyleTTS2 hanya gagal (dengan pesan
jelas) saat benar-benar dipakai untuk sintesis, konsisten dengan pola
graceful degradation binary hilang pada Piper/eSpeak NG.

``styletts2``/``torch`` SENGAJA TIDAK ditambahkan ke ``requirements.txt``
(dependency wajib project) — keduanya opsional & berat (ratusan MB - GB,
mensyaratkan toolchain build untuk `monotonic_align`, per riset Phase 9),
menginstallnya wajib untuk SEMUA deployment akan melanggar prinsip "engine
tambahan tidak memaksa pengguna menginstall" (Phase 7). Operator yang ingin
memakai StyleTTS2 menginstallnya terpisah.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from pathlib import Path

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import (
    TTSEngineNotAvailableError,
    TTSGenerationError,
    VoiceNotFoundError,
)
from announcement_server.core.retry import retry_with_backoff
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_capability import EngineCapability
from announcement_server.tts.voice_profile import VoiceProfile

logger = logging.getLogger(__name__)

# Default parameter style StyleTTS2 -- SAMA PERSIS dengan default resmi paket
# referensi (`inference()`, lihat riset Phase 9). TIDAK dieksposisikan
# per-request maupun per-config (keputusan Phase 10: tidak terbukti perlu).
_DEFAULT_ALPHA = 0.3
_DEFAULT_BETA = 0.7
_DEFAULT_EMBEDDING_SCALE = 1

# Sample rate output resmi paket referensi StyleTTS2 (terdokumentasi, bukan
# tebakan -- lihat riset Phase 9) -- dipakai juga sebagai `native_sample_rate`
# pada EngineCapability di bawah.
_OUTPUT_SAMPLE_RATE = 24000


class StyleTTS2Engine(TTSEngine):
    """Engine TTS berbasis StyleTTS2 (voice cloning dari referensi audio terkurasi)."""

    def __init__(self, config: TTSConfig) -> None:
        self._checkpoint_path = config.styletts2_checkpoint_path
        self._config_path = config.styletts2_config_path
        self._voices_dir = Path(config.styletts2_voices_dir)
        self._diffusion_steps = config.styletts2_diffusion_steps
        self._max_retries = config.max_retries
        self._retry_backoff_seconds = config.retry_backoff_seconds

        # Lazy load (keputusan Phase 10/11): model TIDAK dimuat di sini.
        # Loading checkpoint StyleTTS2 berat (PyTorch, bisa berukuran GB) dan
        # TIDAK BOLEH memblokir `TTSEngineManager.__init__` yang sinkron --
        # dimuat sekali pada panggilan pertama (`synthesize()` atau
        # `initialize()`, mana pun lebih dulu), lalu dipakai ulang.
        self._model: object | None = None
        self._model_lock = asyncio.Lock()

    def _load_model_sync(self) -> object:
        """Memuat checkpoint StyleTTS2 -- operasi BERAT, HARUS dipanggil lewat
        ``asyncio.to_thread`` (dilakukan oleh pemanggil, lihat ``_ensure_model_loaded``).

        Mengikuti API resmi paket referensi StyleTTS2 (``styletts2.tts.StyleTTS2``,
        lihat riset Phase 9): constructor menerima ``model_checkpoint_path``/
        ``config_path`` eksplisit -- kita SELALU memberikan path eksplisit
        (bukan ``None``) agar tetap offline-first, konsisten dengan Piper/eSpeak NG
        (tidak bergantung pada auto-download saat runtime).
        """
        from styletts2 import tts  # import lokal SENGAJA -- lihat docstring modul

        return tts.StyleTTS2(
            model_checkpoint_path=self._checkpoint_path,
            config_path=self._config_path,
        )

    async def _ensure_model_loaded(self) -> object:
        if self._model is not None:
            return self._model
        async with self._model_lock:
            # Double-checked locking: dua request pertama yang datang bersamaan
            # sebelum model pertama selesai dimuat tidak boleh memicu load ganda.
            if self._model is None:
                logger.info("StyleTTS2Engine: memuat model dari '%s'...", self._checkpoint_path)
                try:
                    self._model = await asyncio.to_thread(self._load_model_sync)
                except Exception as exc:
                    raise TTSEngineNotAvailableError(
                        f"Gagal memuat model StyleTTS2 (checkpoint='{self._checkpoint_path}', "
                        f"config='{self._config_path}'): {exc}",
                        details={"checkpoint_path": self._checkpoint_path, "config_path": self._config_path},
                    ) from exc
                logger.info("StyleTTS2Engine: model berhasil dimuat.")
        return self._model

    def _resolve_voice_path(self, voice: str) -> Path:
        """Resolusi voice -> path file referensi audio, dengan proteksi path traversal
        yang SAMA PERSIS dengan ``AudioAssetResolver`` (containment check terhadap hasil
        ``.resolve()``, bukan cek string ``../`` semata -- lihat audit RC1-5)."""
        voices_dir_resolved = self._voices_dir.resolve()
        candidate = (self._voices_dir / f"{voice}.wav").resolve()
        if candidate != voices_dir_resolved and voices_dir_resolved not in candidate.parents:
            raise VoiceNotFoundError(f"Voice '{voice}' tidak valid.", details={"requested_voice": voice})

        if not candidate.is_file():
            available = sorted(p.stem for p in voices_dir_resolved.glob("*.wav")) if voices_dir_resolved.exists() else []
            raise VoiceNotFoundError(
                f"Voice '{voice}' tidak ditemukan pada StyleTTS2 (voices_dir='{self._voices_dir}').",
                details={"requested_voice": voice, "available_voices": available},
            )
        return candidate

    @staticmethod
    def _numpy_to_wav_bytes(audio_array: object, sample_rate: int) -> bytes:
        """Mengonversi output ``inference()`` StyleTTS2 (numpy array float, lihat riset
        Phase 9) menjadi WAV PCM 16-bit -- format yang SAMA dipakai seluruh engine lain
        di project ini (Piper/eSpeak NG), agar `AudioProcessor`/cache/playback generic
        tetap bekerja tanpa perubahan apa pun."""
        import numpy as np  # import lokal SENGAJA -- lihat docstring modul

        clipped = np.clip(np.asarray(audio_array, dtype=np.float32), -1.0, 1.0)
        pcm16 = (clipped * 32767).astype(np.int16)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm16.tobytes())
        return buffer.getvalue()

    def _run_inference_sync(self, model: object, text: str, voice_path: Path) -> bytes:
        audio_array = model.inference(
            text,
            target_voice_path=str(voice_path),
            alpha=_DEFAULT_ALPHA,
            beta=_DEFAULT_BETA,
            diffusion_steps=self._diffusion_steps,
            embedding_scale=_DEFAULT_EMBEDDING_SCALE,
            output_sample_rate=_OUTPUT_SAMPLE_RATE,
        )
        return self._numpy_to_wav_bytes(audio_array, _OUTPUT_SAMPLE_RATE)

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:  # noqa: ARG002 - `speed` diterima
        # sesuai kontrak TTSEngine tapi SENGAJA diabaikan (lihat docstring modul & riset Phase 9/10:
        # StyleTTS2 tidak punya kontrol speed pada API inference resminya).
        return await retry_with_backoff(
            lambda: self._synthesize_once(text=text, voice=voice),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
            retry_on=(TTSGenerationError,),
            operation_name=f"StyleTTS2 synthesize(voice={voice})",
        )

    async def _synthesize_once(self, *, text: str, voice: str) -> bytes:
        # Resolusi voice & load model dilakukan DI LUAR retry scope -- keduanya kegagalan
        # PERMANEN (voice salah / model gagal dimuat tidak akan berbeda hasilnya jika
        # diulang), persis pola VoiceNotFoundError/TTSEngineNotAvailableError pada
        # Piper/eSpeak NG yang juga tidak masuk `retry_on`.
        voice_path = self._resolve_voice_path(voice)
        model = await self._ensure_model_loaded()

        try:
            return await asyncio.to_thread(self._run_inference_sync, model, text, voice_path)
        except Exception as exc:
            raise TTSGenerationError(
                f"StyleTTS2 gagal mensintesis audio untuk voice '{voice}': {exc}",
                details={"voice": voice},
            ) from exc

    async def list_voices(self) -> list[VoiceProfile]:
        """Voice Discovery StyleTTS2: scan ``styletts2_voices_dir`` untuk file ``.wav``
        -- mekanisme YANG SAMA dengan resolusi voice saat sintesis di atas
        (``_resolve_voice_path``), persis pola ``PiperEngine.list_voices()``.
        TIDAK ADA daftar voice yang di-hardcode."""
        return await asyncio.to_thread(self._discover_voices_sync)

    def _discover_voices_sync(self) -> list[VoiceProfile]:
        if not self._voices_dir.exists():
            return []

        voices: list[VoiceProfile] = []
        for wav_path in sorted(self._voices_dir.glob("*.wav")):
            voices.append(
                VoiceProfile(
                    id=wav_path.stem,
                    engine="styletts2",
                    name=wav_path.stem,
                    language=None,  # Tidak dapat diketahui dari file audio referensi -- tidak ditebak.
                    gender=None,  # Sama -- tidak ditebak (berbeda dari eSpeak NG yang punya info gender native).
                    source=str(wav_path),
                    available=True,
                    metadata={},
                )
            )
        return voices

    async def get_capability(self) -> EngineCapability:
        """Kapabilitas StyleTTS2 (Phase 12): berbeda dari Piper MAUPUN eSpeak NG --
        StyleTTS2 TIDAK mendukung speed generic sama sekali (tidak seperti Piper/eSpeak
        NG yang sama-sama True), sementara `native_sample_rate` terisi PASTI (24000 Hz,
        terdokumentasi resmi) -- berbeda dari Piper/eSpeak NG yang sama-sama None
        (bervariasi/tidak terverifikasi). Ini membuktikan EngineCapability benar-benar
        merepresentasikan perbedaan NYATA antar-3 engine, bukan nilai seragam."""
        return EngineCapability(
            supports_speed=False,  # Tidak ada parameter speed pada inference() resmi StyleTTS2.
            supports_native_pitch=False,
            supports_native_volume=False,
            supports_ssml=False,
            offline=True,
            max_text_length=None,  # Tidak terdokumentasi resmi -- tidak ditebak.
            native_sample_rate=_OUTPUT_SAMPLE_RATE,  # 24000 Hz -- default resmi terdokumentasi (riset Phase 9).
        )

    async def initialize(self) -> None:
        """Lifecycle hook (kontrak sudah ada sejak fase sebelumnya, lihat `engine_base.py`).

        CATATAN: hook ini SAAT INI belum dipanggil oleh `TTSEngineManager`/`TTSService`
        mana pun (tidak ada wiring Core baru pada Phase 12 -- di luar scope, lihat Phase 11).
        Implementasi di sini murni memenuhi kontrak secara BENAR untuk kemungkinan wiring
        di fase mendatang: memicu load model lebih awal (bukan menunggu request pertama).
        Idempotent & aman dipanggil berulang (`_ensure_model_loaded` sudah menangani ini).
        """
        await self._ensure_model_loaded()

    async def shutdown(self) -> None:
        """Melepaskan referensi model yang sudah dimuat (jika ada) agar memory/VRAM
        dapat dibebaskan oleh garbage collector -- BERBEDA dari Piper/eSpeak NG yang
        `shutdown()`-nya tetap no-op (keduanya tidak pernah memegang resource yang
        bertahan). Aman dipanggil walau model belum pernah dimuat sama sekali (idempotent).
        """
        async with self._model_lock:
            if self._model is not None:
                logger.info("StyleTTS2Engine: melepaskan model dari memory.")
                self._model = None
