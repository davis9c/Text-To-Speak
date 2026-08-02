"""Unit test untuk PiperEngine.

Karena binary Piper asli tidak tersedia di lingkungan CI/sandbox (dan tidak
didistribusikan bersama repo ini), test di sini memakai *fake piper
executable* — sebuah script Python kecil yang meniru perilaku CLI Piper
(baca teks dari stdin, tulis file WAV ke --output_file, exit code sesuai
skenario). Ini memvalidasi seluruh "plumbing" subprocess (argumen yang
dikirim, penanganan stdin/stdout/stderr, timeout, error handling) tanpa
bergantung pada instalasi Piper yang sesungguhnya.
"""

from __future__ import annotations

import stat
import sys
import wave
from pathlib import Path

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import (
    TTSEngineNotAvailableError,
    TTSGenerationError,
    VoiceNotFoundError,
)
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.piper_engine import PiperEngine

FAKE_PIPER_SCRIPT = '''#!{python_executable}
import sys
import wave
from pathlib import Path

args = sys.argv[1:]

def get_arg(flag):
    return args[args.index(flag) + 1]

# Rekam argumen CLI yang benar-benar diterima + path temp dir yang dipakai,
# agar test bisa memverifikasi mapping speed->length_scale dan cleanup temp
# dir TANPA menduplikasi logic PiperEngine di sisi test.
captured_path = Path(__file__).parent / "captured_args.txt"
output_file = get_arg("--output_file")
captured_path.write_text(
    repr(args) + "\\n" + str(Path(output_file).parent)
)

text = sys.stdin.read()

if "FAIL_EXIT_CODE" in text:
    sys.stderr.write("simulasi kegagalan piper\\n")
    sys.exit(1)

if "FAIL_TIMEOUT" in text:
    import time
    time.sleep(5)
    sys.exit(0)

with wave.open(output_file, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(b"\\x00\\x00" * 100)
sys.exit(0)
'''


@pytest.fixture()
def models_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "test_voice.onnx").write_bytes(b"dummy_model")
    (directory / "test_voice.onnx.json").write_text("{}")
    return directory


@pytest.fixture()
def fake_piper_binary(tmp_path: Path) -> Path:
    script_path = tmp_path / "fake_piper.py"
    script_path.write_text(FAKE_PIPER_SCRIPT.format(python_executable=sys.executable))
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script_path


@pytest.fixture()
def tts_config(fake_piper_binary: Path, models_dir: Path) -> TTSConfig:
    return TTSConfig(
        engine="piper",
        piper_binary_path=str(fake_piper_binary),
        piper_models_dir=str(models_dir),
        generation_timeout_seconds=2.0,
    )


async def test_synthesize_success_returns_wav_bytes(tts_config: TTSConfig) -> None:
    engine = PiperEngine(tts_config)
    audio_bytes = await engine.synthesize(text="Halo dunia", voice="test_voice", speed=1.0)

    assert isinstance(audio_bytes, bytes)
    assert audio_bytes.startswith(b"RIFF")  # magic bytes header WAV


async def test_synthesize_unknown_voice_raises_voice_not_found(tts_config: TTSConfig) -> None:
    engine = PiperEngine(tts_config)
    with pytest.raises(VoiceNotFoundError) as exc_info:
        await engine.synthesize(text="Halo", voice="voice_yang_tidak_ada", speed=1.0)
    assert exc_info.value.details["requested_voice"] == "voice_yang_tidak_ada"
    assert "test_voice" in exc_info.value.details["available_voices"]


async def test_synthesize_missing_binary_raises_engine_not_available(models_dir: Path) -> None:
    config = TTSConfig(
        engine="piper",
        piper_binary_path="/path/tidak/ada/piper_binary_xyz",
        piper_models_dir=str(models_dir),
    )
    engine = PiperEngine(config)
    with pytest.raises(TTSEngineNotAvailableError):
        await engine.synthesize(text="Halo", voice="test_voice", speed=1.0)


async def test_synthesize_nonzero_exit_code_raises_generation_error(tts_config: TTSConfig) -> None:
    engine = PiperEngine(tts_config)
    with pytest.raises(TTSGenerationError) as exc_info:
        await engine.synthesize(text="FAIL_EXIT_CODE trigger", voice="test_voice", speed=1.0)
    assert "stderr" in exc_info.value.details


async def test_synthesize_timeout_raises_generation_error(tts_config: TTSConfig) -> None:
    tts_config.generation_timeout_seconds = 0.5  # fake script sengaja sleep 5 detik
    engine = PiperEngine(tts_config)
    with pytest.raises(TTSGenerationError):
        await engine.synthesize(text="FAIL_TIMEOUT trigger", voice="test_voice", speed=1.0)


async def test_synthesize_speed_is_inverted_to_length_scale(tts_config: TTSConfig, models_dir: Path) -> None:
    """speed=2.0 (lebih cepat) harus dikirim sebagai --length_scale 0.5 (Piper: kecil = cepat)."""
    engine = PiperEngine(tts_config)
    # speed tinggi tidak boleh membuat error; hanya memverifikasi tidak exception
    # dan audio tetap valid (perilaku length_scale sesungguhnya diverifikasi via kode, bukan fake script).
    audio_bytes = await engine.synthesize(text="Cepat", voice="test_voice", speed=2.0)
    assert audio_bytes.startswith(b"RIFF")


# --- V2 Phase 3 — audit tambahan: kontrak, mapping parameter, cleanup -------


def test_piper_engine_satisfies_tts_engine_contract() -> None:
    """PiperEngine HARUS mengimplementasikan interface generic TTSEngine (Strategy Pattern)."""
    assert issubclass(PiperEngine, TTSEngine)
    assert callable(getattr(PiperEngine, "synthesize", None))


@pytest.mark.parametrize(
    ("speed", "expected_length_scale"),
    [
        (2.0, 0.5),  # 2x lebih cepat -> length_scale setengahnya (Piper: kecil = cepat)
        (1.0, 1.0),  # speed normal -> length_scale normal (tidak ada perubahan, sama seperti V1)
        (0.5, 2.0),  # 2x lebih lambat -> length_scale dua kali lipat
    ],
)
async def test_synthesize_sends_exact_inverted_length_scale_to_piper_cli(
    tts_config: TTSConfig, speed: float, expected_length_scale: float
) -> None:
    """Memverifikasi argumen `--length_scale` yang BENAR-BENAR dikirim ke CLI Piper (bukan hanya
    'tidak error' seperti test sebelumnya) — memastikan mapping speed->length_scale (Piper-specific,
    lihat docstring PiperEngine._synthesize_once) tidak berubah dari behavior V1."""
    engine = PiperEngine(tts_config)
    await engine.synthesize(text="Cek argumen", voice="test_voice", speed=speed)

    captured_file = Path(tts_config.piper_binary_path).parent / "captured_args.txt"
    captured_args_repr, _temp_dir_line = captured_file.read_text().splitlines()
    captured_args: list[str] = eval(captured_args_repr)  # noqa: S307 - literal list produced by fixture kita sendiri

    length_scale_index = captured_args.index("--length_scale") + 1
    assert float(captured_args[length_scale_index]) == pytest.approx(expected_length_scale, abs=1e-4)


async def test_synthesize_cleans_up_temp_directory_after_success(tts_config: TTSConfig) -> None:
    """Direktori temporary yang dipakai Piper untuk file output HARUS terhapus setelah
    synthesize() selesai — memverifikasi `tempfile.TemporaryDirectory` context manager benar-benar
    membersihkan resource, bukan sekadar 'tidak error' seperti test lain di file ini."""
    engine = PiperEngine(tts_config)
    await engine.synthesize(text="Cek cleanup", voice="test_voice", speed=1.0)

    captured_file = Path(tts_config.piper_binary_path).parent / "captured_args.txt"
    _captured_args_repr, temp_dir_used = captured_file.read_text().splitlines()

    assert not Path(temp_dir_used).exists(), (
        f"Temp directory '{temp_dir_used}' masih ada setelah synthesize() selesai — "
        "cleanup tempfile.TemporaryDirectory gagal/bocor."
    )


async def test_synthesize_cleans_up_temp_directory_even_after_generation_failure(tts_config: TTSConfig) -> None:
    """Cleanup temp directory harus tetap terjadi walau Piper gagal (exit code non-zero) —
    tidak boleh ada temp directory yang bocor saat error."""
    engine = PiperEngine(tts_config)
    with pytest.raises(TTSGenerationError):
        await engine.synthesize(text="FAIL_EXIT_CODE trigger", voice="test_voice", speed=1.0)

    captured_file = Path(tts_config.piper_binary_path).parent / "captured_args.txt"
    _captured_args_repr, temp_dir_used = captured_file.read_text().splitlines()

    assert not Path(temp_dir_used).exists()
