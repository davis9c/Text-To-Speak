"""Test untuk EspeakEngine (V2 Phase 7 — engine open-source kedua).

Memakai skrip Python palsu yang berperan sebagai binary eSpeak NG (pola yang
SAMA PERSIS dengan `tests/test_piper_engine.py`), agar test deterministik
dan tidak bergantung pada instalasi eSpeak NG asli maupun akses jaringan.

CATATAN JUJUR: karena sandbox ini tidak memiliki binary eSpeak NG asli
untuk diverifikasi, format output `--voices` yang disimulasikan skrip palsu
di bawah ini didasarkan pada dokumentasi/format yang dikenal luas, bukan
hasil eksekusi nyata -- sebaiknya diverifikasi ulang terhadap binary asli.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import (
    TTSEngineNotAvailableError,
    TTSGenerationError,
    VoiceNotFoundError,
)
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.espeak_engine import EspeakEngine

from tests.conftest import make_fake_executable

FAKE_ESPEAK_SCRIPT = '''#!{python_executable}
import sys
import wave
from pathlib import Path

args = sys.argv[1:]

def get_arg(flag):
    return args[args.index(flag) + 1]

if "--voices" in args:
    sys.stdout.write(
        "Pty Language       Age/Gender VoiceName          File                 Other_Languages\\n"
        " 5  en-us               M  english-us         en/en-us\\n"
        " 5  id                   F  indonesian         id/id\\n"
        " 5  zh                   -  chinese            zh/zh\\n"
        " 5  xx                50M  oddformat          xx/xx\\n"
    )
    sys.exit(0)

captured_path = Path(__file__).parent / "captured_args.txt"
output_file = get_arg("-w")
voice = get_arg("-v")
captured_path.write_text(repr(args) + "\\n" + str(Path(output_file).parent))

text = sys.stdin.read()

if "FAIL_EXIT_CODE" in text:
    sys.stderr.write("simulasi kegagalan umum eSpeak NG\\n")
    sys.exit(1)

if "FAIL_TIMEOUT" in text:
    import time
    sys.stdout.close()
    sys.stderr.close()
    time.sleep(5)
    sys.exit(0)

if voice == "unknown_voice_trigger":
    sys.stderr.write("Unknown voice name: 'unknown_voice_trigger'\\n")
    sys.exit(1)

with wave.open(output_file, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(b"\\x00\\x00" * 100)
sys.exit(0)
'''


@pytest.fixture()
def fake_espeak_binary(tmp_path: Path) -> Path:
    return make_fake_executable(FAKE_ESPEAK_SCRIPT.format(python_executable=sys.executable), "fake_espeak", tmp_path)


@pytest.fixture()
def tts_config(fake_espeak_binary: Path) -> TTSConfig:
    return TTSConfig(
        engine="espeak",
        espeak_binary_path=str(fake_espeak_binary),
        generation_timeout_seconds=2.0,
    )


# --- synthesize() -------------------------------------------------------------


async def test_synthesize_success_returns_wav_bytes(tts_config: TTSConfig) -> None:
    engine = EspeakEngine(tts_config)
    audio_bytes = await engine.synthesize(text="Halo dunia", voice="en-us", speed=1.0)
    assert isinstance(audio_bytes, bytes)
    assert audio_bytes.startswith(b"RIFF")


async def test_synthesize_missing_binary_raises_engine_not_available() -> None:
    config = TTSConfig(engine="espeak", espeak_binary_path="/path/tidak/ada/espeak_xyz")
    engine = EspeakEngine(config)
    with pytest.raises(TTSEngineNotAvailableError):
        await engine.synthesize(text="Halo", voice="en-us", speed=1.0)


async def test_synthesize_nonzero_exit_code_raises_generation_error(tts_config: TTSConfig) -> None:
    engine = EspeakEngine(tts_config)
    with pytest.raises(TTSGenerationError) as exc_info:
        await engine.synthesize(text="FAIL_EXIT_CODE trigger", voice="en-us", speed=1.0)
    assert "stderr" in exc_info.value.details


async def test_synthesize_timeout_raises_generation_error(tts_config: TTSConfig) -> None:
    tts_config.generation_timeout_seconds = 0.5  # fake script sengaja sleep 5 detik
    engine = EspeakEngine(tts_config)
    with pytest.raises(TTSGenerationError):
        await engine.synthesize(text="FAIL_TIMEOUT trigger", voice="en-us", speed=1.0)


async def test_synthesize_unrecognized_voice_raises_voice_not_found(tts_config: TTSConfig) -> None:
    """Fake script mensimulasikan pesan stderr 'Unknown voice name' -- lihat catatan jujur
    di docstring modul EspeakEngine soal ketidakpastian perilaku exact binary asli."""
    engine = EspeakEngine(tts_config)
    with pytest.raises(VoiceNotFoundError) as exc_info:
        await engine.synthesize(text="Halo", voice="unknown_voice_trigger", speed=1.0)
    assert exc_info.value.details["requested_voice"] == "unknown_voice_trigger"


@pytest.mark.parametrize(
    ("speed", "expected_wpm"),
    [
        (1.0, 175),  # baseline kita sendiri (lihat _BASELINE_WORDS_PER_MINUTE)
        (2.0, 350),
        (0.5, 88),  # round(175 * 0.5) = 87.5 -> round-half-to-even Python = 88
    ],
)
async def test_synthesize_sends_expected_words_per_minute(tts_config: TTSConfig, speed: float, expected_wpm: int) -> None:
    engine = EspeakEngine(tts_config)
    await engine.synthesize(text="Cek argumen", voice="en-us", speed=speed)

    captured_file = Path(tts_config.espeak_binary_path).parent / "captured_args.txt"
    captured_args_repr, _temp_dir_line = captured_file.read_text().splitlines()
    captured_args: list[str] = eval(captured_args_repr)  # noqa: S307 - literal list dari fixture kita sendiri

    wpm_index = captured_args.index("-s") + 1
    assert int(captured_args[wpm_index]) == expected_wpm


async def test_synthesize_cleans_up_temp_directory_after_success(tts_config: TTSConfig) -> None:
    engine = EspeakEngine(tts_config)
    await engine.synthesize(text="Cek cleanup", voice="en-us", speed=1.0)

    captured_file = Path(tts_config.espeak_binary_path).parent / "captured_args.txt"
    _captured_args_repr, temp_dir_used = captured_file.read_text().splitlines()
    assert not Path(temp_dir_used).exists()


# --- list_voices() -------------------------------------------------------------


async def test_list_voices_parses_native_voices_output(tts_config: TTSConfig) -> None:
    engine = EspeakEngine(tts_config)
    voices = {voice.id: voice for voice in await engine.list_voices()}

    assert set(voices) == {"en-us", "id", "zh", "xx"}
    assert all(voice.engine == "espeak" for voice in voices.values())
    assert all(voice.available for voice in voices.values())


async def test_list_voices_extracts_real_gender_when_recognized(tts_config: TTSConfig) -> None:
    """Berbeda dari Piper (gender selalu None): eSpeak NG SECARA NATIVE menyediakan gender,
    jadi HARUS diekstrak apa adanya jika kolomnya 'M'/'F' yang dikenal."""
    engine = EspeakEngine(tts_config)
    voices = {voice.id: voice for voice in await engine.list_voices()}

    assert voices["en-us"].gender == "male"
    assert voices["id"].gender == "female"


async def test_list_voices_does_not_invent_gender_for_unrecognized_code(tts_config: TTSConfig) -> None:
    engine = EspeakEngine(tts_config)
    voices = {voice.id: voice for voice in await engine.list_voices()}

    assert voices["zh"].gender is None  # kolom "-" -> tidak diketahui, bukan ditebak
    assert voices["xx"].gender is None  # kolom "50M" tidak dikenali format standarnya -> tidak ditebak
    assert voices["xx"].metadata.get("raw_age_gender") == "50M"


async def test_list_voices_returns_empty_when_binary_missing() -> None:
    config = TTSConfig(engine="espeak", espeak_binary_path="/path/tidak/ada/espeak_xyz")
    engine = EspeakEngine(config)
    assert await engine.list_voices() == []


async def test_get_voice_uses_default_lookup(tts_config: TTSConfig) -> None:
    engine = EspeakEngine(tts_config)
    found = await engine.get_voice("id")
    assert found is not None
    assert found.language == "id"
    assert await engine.get_voice("voice_tidak_ada") is None


# --- get_capability() -----------------------------------------------------------


async def test_get_capability_reflects_espeak_native_features(tts_config: TTSConfig) -> None:
    """eSpeak NG mendukung pitch/volume/SSML native lewat CLI -- BERBEDA dari Piper
    (yang seluruhnya False untuk field ini), membuktikan kapabilitas benar-benar per-engine."""
    engine = EspeakEngine(tts_config)
    capability = await engine.get_capability()

    assert capability.supports_speed is True
    assert capability.supports_native_pitch is True
    assert capability.supports_native_volume is True
    assert capability.supports_ssml is True
    assert capability.offline is True


# --- kontrak TTSEngine -----------------------------------------------------------


def test_espeak_engine_satisfies_tts_engine_contract() -> None:
    assert issubclass(EspeakEngine, TTSEngine)
    assert callable(getattr(EspeakEngine, "synthesize", None))
