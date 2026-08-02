"""Test untuk StyleTTS2Engine (Phase 12).

`styletts2`/`torch` adalah dependency OPSIONAL yang TIDAK terinstall di
lingkungan test standar (berat, lihat docstring `styletts2_engine.py`). Test
yang menyentuh jalur inference sesungguhnya memakai TEKNIK INJEKSI MODULE
PALSU ke `sys.modules['styletts2']` (via `monkeypatch`, otomatis dibersihkan
setelah tiap test) -- ini menguji KODE PRODUKSI YANG ASLI (lazy import +
pemanggilan `model.inference(...)` yang sesungguhnya), bukan sekadar men-skip
test tersebut.
"""

from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import (
    TTSEngineNotAvailableError,
    TTSGenerationError,
    VoiceNotFoundError,
)
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.styletts2_engine import StyleTTS2Engine


class _FakeStyleTTS2Model:
    """Meniru `styletts2.tts.StyleTTS2` -- menyimpan argumen yang diterima agar
    dapat diverifikasi test, mengembalikan audio array palsu (bukan hasil ML asli)."""

    def __init__(self, model_checkpoint_path=None, config_path=None):
        self.model_checkpoint_path = model_checkpoint_path
        self.config_path = config_path
        self.inference_calls: list[dict] = []

    def inference(self, text, **kwargs):
        self.inference_calls.append({"text": text, **kwargs})
        return np.zeros(2400, dtype=np.float32)  # 0.1 detik senyap @ 24000 Hz


class _FailingStyleTTS2Model:
    def __init__(self, model_checkpoint_path=None, config_path=None):
        pass

    def inference(self, text, **kwargs):
        raise RuntimeError("simulasi kegagalan inference StyleTTS2")


def _inject_fake_styletts2_module(monkeypatch: pytest.MonkeyPatch, model_class: type) -> types.SimpleNamespace:
    fake_tts_module = types.SimpleNamespace(StyleTTS2=model_class)
    fake_package = types.SimpleNamespace(tts=fake_tts_module)
    monkeypatch.setitem(sys.modules, "styletts2", fake_package)
    monkeypatch.setitem(sys.modules, "styletts2.tts", fake_tts_module)
    return fake_tts_module


@pytest.fixture()
def fake_styletts2_module(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    return _inject_fake_styletts2_module(monkeypatch, _FakeStyleTTS2Model)


@pytest.fixture()
def fake_failing_styletts2_module(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    return _inject_fake_styletts2_module(monkeypatch, _FailingStyleTTS2Model)


@pytest.fixture()
def voices_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "voices"
    directory.mkdir()
    (directory / "narrator_calm.wav").write_bytes(b"dummy-wav-bytes")
    (directory / "narrator_energetic.wav").write_bytes(b"dummy-wav-bytes")
    return directory


@pytest.fixture()
def tts_config(voices_dir: Path, tmp_path: Path) -> TTSConfig:
    return TTSConfig(
        engine="styletts2",
        styletts2_checkpoint_path=str(tmp_path / "model.pth"),
        styletts2_config_path=str(tmp_path / "config.yml"),
        styletts2_voices_dir=str(voices_dir),
        styletts2_diffusion_steps=3,
    )


# --- Kontrak TTSEngine -----------------------------------------------------


def test_styletts2_engine_satisfies_tts_engine_contract() -> None:
    assert issubclass(StyleTTS2Engine, TTSEngine)


# --- list_voices() (murni file scan -- tidak butuh styletts2/torch sama sekali) --


async def test_list_voices_discovers_wav_files_from_disk(tts_config: TTSConfig) -> None:
    engine = StyleTTS2Engine(tts_config)
    voices = {voice.id: voice for voice in await engine.list_voices()}

    assert set(voices) == {"narrator_calm", "narrator_energetic"}
    assert all(voice.engine == "styletts2" for voice in voices.values())
    assert all(voice.available for voice in voices.values())


async def test_list_voices_never_invents_language_or_gender(tts_config: TTSConfig) -> None:
    """File audio referensi tidak menyediakan metadata bahasa/gender -- tidak ditebak."""
    engine = StyleTTS2Engine(tts_config)
    voices = await engine.list_voices()
    assert all(voice.language is None for voice in voices)
    assert all(voice.gender is None for voice in voices)


async def test_list_voices_returns_empty_when_voices_dir_missing(tmp_path: Path) -> None:
    config = TTSConfig(engine="styletts2", styletts2_voices_dir=str(tmp_path / "tidak_ada"))
    engine = StyleTTS2Engine(config)
    assert await engine.list_voices() == []


async def test_get_voice_uses_default_lookup(tts_config: TTSConfig) -> None:
    engine = StyleTTS2Engine(tts_config)
    found = await engine.get_voice("narrator_calm")
    assert found is not None
    assert found.source.endswith("narrator_calm.wav")
    assert await engine.get_voice("voice_tidak_ada") is None


# --- Path traversal & voice tidak ditemukan --------------------------------


async def test_synthesize_rejects_path_traversal_voice(tts_config: TTSConfig) -> None:
    engine = StyleTTS2Engine(tts_config)
    with pytest.raises(VoiceNotFoundError):
        await engine.synthesize(text="Halo", voice="../../../etc/passwd", speed=1.0)


async def test_synthesize_unknown_voice_raises_voice_not_found(tts_config: TTSConfig) -> None:
    engine = StyleTTS2Engine(tts_config)
    with pytest.raises(VoiceNotFoundError) as exc_info:
        await engine.synthesize(text="Halo", voice="voice_tidak_ada", speed=1.0)
    assert "narrator_calm" in exc_info.value.details["available_voices"]


# --- get_capability() (murni data, tidak butuh styletts2/torch) ----------------


async def test_get_capability_reflects_styletts2_unique_profile(tts_config: TTSConfig) -> None:
    """Berbeda dari Piper MAUPUN eSpeak NG: speed tidak didukung, sample rate pasti diketahui
    (24000 Hz terdokumentasi resmi) -- membuktikan Capability benar-benar per-engine."""
    engine = StyleTTS2Engine(tts_config)
    capability = await engine.get_capability()

    assert capability.supports_speed is False
    assert capability.supports_native_pitch is False
    assert capability.supports_native_volume is False
    assert capability.native_sample_rate == 24000
    assert capability.offline is True


# --- synthesize() sukses (lewat injeksi module styletts2 palsu) ----------------


async def test_synthesize_success_returns_wav_bytes(tts_config: TTSConfig, fake_styletts2_module) -> None:
    engine = StyleTTS2Engine(tts_config)
    audio_bytes = await engine.synthesize(text="Halo dunia", voice="narrator_calm", speed=1.0)
    assert audio_bytes.startswith(b"RIFF")


async def test_synthesize_ignores_speed_parameter(tts_config: TTSConfig, fake_styletts2_module) -> None:
    """`speed` diterima sesuai kontrak tapi TIDAK diteruskan ke inference() -- StyleTTS2
    tidak punya parameter speed pada API resminya (riset Phase 9, bukan dugaan)."""
    engine = StyleTTS2Engine(tts_config)
    await engine.synthesize(text="Cepat atau lambat", voice="narrator_calm", speed=2.5)

    model = await engine._ensure_model_loaded()
    assert "speed" not in model.inference_calls[0]


async def test_synthesize_uses_configured_diffusion_steps(tts_config: TTSConfig, fake_styletts2_module) -> None:
    engine = StyleTTS2Engine(tts_config)
    await engine.synthesize(text="Cek diffusion steps", voice="narrator_calm", speed=1.0)

    model = await engine._ensure_model_loaded()
    assert model.inference_calls[0]["diffusion_steps"] == 3  # dari tts_config (styletts2_diffusion_steps=3)


async def test_synthesize_reuses_loaded_model_across_calls(tts_config: TTSConfig, fake_styletts2_module) -> None:
    """Model HARUS dimuat sekali saja (memoized), bukan setiap panggilan synthesize()."""
    engine = StyleTTS2Engine(tts_config)
    await engine.synthesize(text="Panggilan pertama", voice="narrator_calm", speed=1.0)
    first_model = engine._model
    await engine.synthesize(text="Panggilan kedua", voice="narrator_energetic", speed=1.0)

    assert engine._model is first_model  # instance model SAMA -- tidak dimuat ulang
    assert len(first_model.inference_calls) == 2


async def test_synthesize_model_not_loaded_until_first_call(tts_config: TTSConfig, fake_styletts2_module) -> None:
    engine = StyleTTS2Engine(tts_config)
    assert engine._model is None  # belum dimuat setelah __init__ (lazy loading, keputusan Phase 10/11)
    await engine.synthesize(text="Halo", voice="narrator_calm", speed=1.0)
    assert engine._model is not None


# --- synthesize() gagal (dependency hilang / inference gagal) ------------------


async def test_synthesize_missing_styletts2_package_raises_engine_not_available(
    tts_config: TTSConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jika package `styletts2` benar-benar tidak terinstall, engine HARUS gagal dengan
    pesan jelas -- BUKAN meng-crash aplikasi (lihat docstring modul soal lazy import)."""
    monkeypatch.delitem(sys.modules, "styletts2", raising=False)
    monkeypatch.delitem(sys.modules, "styletts2.tts", raising=False)

    real_import = builtins.__import__

    def _blocking_import(name, *args, **kwargs):
        if name == "styletts2" or name.startswith("styletts2."):
            raise ImportError("simulasi: package styletts2 tidak terinstall")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)

    engine = StyleTTS2Engine(tts_config)
    with pytest.raises(TTSEngineNotAvailableError):
        await engine.synthesize(text="Halo", voice="narrator_calm", speed=1.0)


async def test_synthesize_inference_failure_raises_generation_error(
    tts_config: TTSConfig, fake_failing_styletts2_module
) -> None:
    engine = StyleTTS2Engine(tts_config)
    with pytest.raises(TTSGenerationError):
        await engine.synthesize(text="Halo", voice="narrator_calm", speed=1.0)


async def test_synthesize_model_load_failure_is_not_retried(
    tts_config: TTSConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTSEngineNotAvailableError (model gagal dimuat) adalah kegagalan PERMANEN --
    TIDAK boleh di-retry (beda dari TTSGenerationError, konsisten dengan Piper/eSpeak NG)."""
    call_count = 0

    class _AlwaysFailingModel:
        def __init__(self, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("checkpoint corrupt")

    _inject_fake_styletts2_module(monkeypatch, _AlwaysFailingModel)

    engine = StyleTTS2Engine(tts_config)
    with pytest.raises(TTSEngineNotAvailableError):
        await engine.synthesize(text="Halo", voice="narrator_calm", speed=1.0)

    assert call_count == 1  # HANYA satu kali percobaan -- bukti tidak di-retry


# --- shutdown() --------------------------------------------------------------


async def test_shutdown_releases_loaded_model(tts_config: TTSConfig, fake_styletts2_module) -> None:
    engine = StyleTTS2Engine(tts_config)
    await engine.synthesize(text="Halo", voice="narrator_calm", speed=1.0)
    assert engine._model is not None

    await engine.shutdown()
    assert engine._model is None


async def test_shutdown_is_safe_when_model_never_loaded(tts_config: TTSConfig) -> None:
    engine = StyleTTS2Engine(tts_config)
    await engine.shutdown()  # TIDAK BOLEH raise apa pun
    assert engine._model is None


# --- initialize() --------------------------------------------------------------


async def test_initialize_eagerly_loads_model(tts_config: TTSConfig, fake_styletts2_module) -> None:
    """Berbeda dari Piper/eSpeak NG (initialize() tetap default no-op): StyleTTS2Engine
    meng-override initialize() untuk memicu load model lebih awal JIKA hook ini suatu
    saat dipanggil (belum di-wire ke Core pada Phase 12 -- lihat docstring modul)."""
    engine = StyleTTS2Engine(tts_config)
    assert engine._model is None
    await engine.initialize()
    assert engine._model is not None
