"""eSpeak NG Engine (V2 Phase 7 — engine open-source kedua).

Implementasi ``TTSEngine`` yang memanggil executable eSpeak NG
(https://github.com/espeak-ng/espeak-ng) sebagai subprocess -- pola yang
SAMA PERSIS dengan ``PiperEngine`` (subprocess asinkron, retry, timeout,
temp file, graceful degradation) sehingga membuktikan kontrak ``TTSEngine``
memang cukup generic untuk lebih dari satu engine nyata.

Kenapa eSpeak NG (evaluasi singkat terhadap kandidat):
  - Open source, lisensi GPL-3.0 (jelas, permisif untuk redistribusi).
  - Berjalan sepenuhnya lokal/offline, tanpa layanan cloud/API key.
  - Windows compatible (tersedia installer/binary resmi untuk Windows).
  - Sudah punya mekanisme discovery voice NATIVE lewat CLI (`--voices`),
    tidak perlu dibuat sendiri -- selaras dengan syarat Phase 7.
  - CLI sederhana (mirip Piper: satu binary, argumen jelas) -- mudah
    diintegrasikan ke kontrak ``TTSEngine`` tanpa SDK/dependency Python
    tambahan.
  - Proyek matang & aktif (dipakai luas di ekosistem aksesibilitas, mis.
    NVDA screen reader, Home Assistant, dll), bukan proyek baru/belum teruji.
  - PERBEDAAN nyata dari Piper (bukti arsitektur multi-engine benar-benar
    fleksibel): eSpeak NG tidak butuh direktori model eksternal (voice
    bawaan binary itu sendiri), dan `--voices` SECARA NATIVE menyediakan
    kolom gender -- sesuatu yang TIDAK dimiliki format config Piper (lihat
    ``PiperEngine.list_voices()`` yang selalu ``gender=None``). Ini
    menunjukkan registry & kontrak generic tetap bekerja walau dua engine
    punya bentuk metadata yang berbeda.

CATATAN JUJUR (keterbatasan implementasi ini): environment sandbox tempat
kode ini ditulis TIDAK memiliki akses jaringan maupun binary eSpeak NG
asli untuk diuji langsung. Parsing berikut didasarkan pada format output
`--voices` eSpeak NG yang terdokumentasi & stabil lintas versi (kolom:
Pty, Language, Age/Gender, VoiceName, File, [Other_Languages]), tetapi
SEBAIKNYA diverifikasi ulang terhadap binary eSpeak NG sungguhan sebelum
dipakai di produksi -- lihat juga test dengan skrip eSpeak NG palsu di
``tests/test_espeak_engine.py`` yang mensimulasikan format ini.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
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

# eSpeak NG tidak mendokumentasikan satu nilai "default wpm" yang berlaku
# universal di semua build/platform -- inilah baseline mapping KITA SENDIRI
# untuk `speed=1.0` (mengikuti pola Piper: `length_scale = 1/speed` juga
# baseline eksplisit, bukan klaim tentang default resmi upstream).
_BASELINE_WORDS_PER_MINUTE = 175
_MIN_WORDS_PER_MINUTE = 80
_MAX_WORDS_PER_MINUTE = 400

_GENDER_CODE_MAP = {"M": "male", "F": "female"}


class EspeakEngine(TTSEngine):
    """Engine TTS berbasis eSpeak NG."""

    def __init__(self, config: TTSConfig) -> None:
        self._binary_path = config.espeak_binary_path
        self._timeout_seconds = config.generation_timeout_seconds
        self._max_retries = config.max_retries
        self._retry_backoff_seconds = config.retry_backoff_seconds

        # Sengaja TIDAK melempar exception di sini walau binary belum ada --
        # graceful degradation yang sama persis dengan PiperEngine (lihat
        # catatan di sana). `shutil.which()` juga mengecek PATH sistem (bukan
        # hanya file lokal), karena default konfigurasi ("espeak-ng") adalah
        # nama binary di PATH, bukan path absolut.
        if shutil.which(self._binary_path) is None and not Path(self._binary_path).is_file():
            logger.warning(
                "eSpeak NG binary tidak ditemukan ('%s', dicek di PATH & sebagai path file). "
                "Endpoint /speak akan tetap menerima request dengan engine='espeak', tetapi item "
                "akan berstatus FAILED saat diproses hingga binary tersedia.",
                self._binary_path,
            )

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        # Pola retry SAMA PERSIS dengan PiperEngine: hanya TTSGenerationError
        # (kegagalan proses transien) yang di-retry -- lihat penjelasan di sana.
        return await retry_with_backoff(
            lambda: self._synthesize_once(text=text, voice=voice, speed=speed),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
            retry_on=(TTSGenerationError,),
            operation_name=f"eSpeak NG synthesize(voice={voice})",
        )

    async def _synthesize_once(self, *, text: str, voice: str, speed: float) -> bytes:
        words_per_minute = round(_BASELINE_WORDS_PER_MINUTE * speed) if speed > 0 else _BASELINE_WORDS_PER_MINUTE
        words_per_minute = max(_MIN_WORDS_PER_MINUTE, min(_MAX_WORDS_PER_MINUTE, words_per_minute))

        with tempfile.TemporaryDirectory(prefix="announcement_tts_espeak_") as tmp_dir:
            output_path = Path(tmp_dir) / "output.wav"
            command = [
                self._binary_path,
                "--stdin",  # baca teks dari stdin (sama seperti pola PiperEngine), bukan argumen CLI
                "-b",
                "1",  # 1 = input UTF-8 (perlu untuk teks non-ASCII, mis. Bahasa Indonesia)
                "-v",
                voice,
                "-s",
                str(words_per_minute),
                "-w",
                str(output_path),
            ]

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise TTSEngineNotAvailableError(
                    f"eSpeak NG binary tidak ditemukan ('{self._binary_path}'). Pastikan "
                    "tts.espeak_binary_path pada config.yaml sudah benar dan eSpeak NG sudah terinstall.",
                ) from exc
            except OSError as exc:
                raise TTSEngineNotAvailableError(f"Gagal menjalankan eSpeak NG: {exc}") from exc

            try:
                _stdout, stderr = await asyncio.wait_for(
                    process.communicate(text.encode("utf-8")),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise TTSGenerationError(
                    f"eSpeak NG timeout setelah {self._timeout_seconds} detik untuk voice '{voice}'.",
                    details={"voice": voice, "timeout_seconds": self._timeout_seconds},
                ) from exc

            stderr_text = stderr.decode("utf-8", errors="replace")

            if process.returncode != 0:
                # CATATAN JUJUR: eSpeak NG tidak selalu membedakan exit-code untuk
                # "voice tidak dikenal" vs kegagalan lain secara konsisten lintas versi
                # (tidak dapat diverifikasi di sandbox ini -- lihat docstring modul).
                # Kita masih mencoba mendeteksi pesan "voice"/"unknown" di stderr agar
                # error yang paling umum (typo nama voice) mendapat pesan yang jelas,
                # tapi fallback ke TTSGenerationError generic untuk kasus lain.
                lowered_stderr = stderr_text.lower()
                if "voice" in lowered_stderr and ("unknown" in lowered_stderr or "not found" in lowered_stderr):
                    raise VoiceNotFoundError(
                        f"Voice '{voice}' tidak dikenali oleh eSpeak NG.",
                        details={"requested_voice": voice, "stderr": stderr_text[:500]},
                    )
                raise TTSGenerationError(
                    f"eSpeak NG gagal menghasilkan audio (exit code {process.returncode}).",
                    details={"stderr": stderr_text[:500]},
                )

            if not output_path.exists():
                raise TTSGenerationError(
                    "eSpeak NG melaporkan sukses (exit code 0) tetapi file output tidak ditemukan.",
                )

            return await asyncio.to_thread(output_path.read_bytes)

    async def list_voices(self) -> list[VoiceProfile]:
        """Voice Discovery eSpeak NG (V2 Phase 7) -- memakai mekanisme NATIVE `--voices`
        milik eSpeak NG sendiri (bukan scan direktori seperti Piper, karena eSpeak NG
        tidak memakai file model eksternal). TIDAK ADA daftar voice yang di-hardcode.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                self._binary_path,
                "--voices",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError):
            # Binary tidak ada -> tidak ada voice yang bisa ditemukan. Konsisten dengan
            # PiperEngine.list_voices() yang mengembalikan [] jika models_dir tidak ada,
            # BUKAN melempar exception (discovery adalah operasi read-only, best-effort).
            return []

        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()
            logger.warning("eSpeak NG '--voices' timeout -- discovery mengembalikan list kosong.")
            return []

        if process.returncode != 0:
            logger.warning("eSpeak NG '--voices' gagal (exit code %s) -- discovery mengembalikan list kosong.", process.returncode)
            return []

        return self._parse_voices_output(stdout.decode("utf-8", errors="replace"))

    def _parse_voices_output(self, raw_output: str) -> list[VoiceProfile]:
        voices: list[VoiceProfile] = []
        lines = raw_output.splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.lower().startswith("pty"):
                continue  # baris kosong atau header kolom

            # Format (terdokumentasikan, lihat docstring modul):
            #   Pty Language Age/Gender VoiceName File [Other_Languages...]
            parts = stripped.split(maxsplit=5)
            if len(parts) < 5:
                logger.warning("Baris output eSpeak NG '--voices' tidak dikenali, dilewati: %r", line)
                continue

            _priority, language_code, age_gender, voice_name, source_file = parts[:5]

            gender = _GENDER_CODE_MAP.get(age_gender.strip().upper())

            voices.append(
                VoiceProfile(
                    id=language_code,
                    engine="espeak",
                    name=voice_name,
                    language=language_code,
                    gender=gender,  # None jika kolom tidak berupa "M"/"F" yang dikenal -- tidak ditebak.
                    source=source_file,
                    available=True,  # Muncul di --voices berarti binary melaporkannya siap dipakai.
                    metadata={"raw_age_gender": age_gender} if gender is None and age_gender != "-" else {},
                )
            )
        return voices

    async def get_capability(self) -> EngineCapability:
        """Kapabilitas eSpeak NG (V2 Phase 7): berbeda nyata dari Piper -- eSpeak NG
        SECARA NATIVE mendukung pitch (`-p`) dan volume/amplitude (`-a`) lewat CLI-nya,
        serta subset SSML dasar (`-m`). CATATAN: integrasi `synthesize()` di atas belum
        memakai flag `-p`/`-a`/`-m` ini (kontrak `TTSEngine.synthesize()` sengaja tidak
        punya parameter pitch/volume/ssml -- lihat docstring `TTSEngine`), field ini
        murni informasional tentang kapabilitas ENGINE itu sendiri, sama seperti
        `PiperEngine.get_capability()`."""
        return EngineCapability(
            supports_speed=True,
            supports_native_pitch=True,
            supports_native_volume=True,
            supports_ssml=True,
            offline=True,
            max_text_length=None,  # eSpeak NG tidak mendokumentasikan batas panjang teks tetap -- tidak ditebak.
            native_sample_rate=None,  # Bervariasi/dapat dikonfigurasi -- tidak diklaim tanpa verifikasi binary asli.
        )
