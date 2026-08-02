"""Unit test untuk EngineFactory."""

from __future__ import annotations

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import TTSEngineNotAvailableError
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.piper_engine import PiperEngine


def test_piper_is_registered_by_default() -> None:
    config = TTSConfig(engine="piper")
    engine = EngineFactory.create(config)
    assert isinstance(engine, PiperEngine)


def test_unknown_engine_raises_not_available_error() -> None:
    config = TTSConfig(engine="engine_yang_tidak_ada")
    with pytest.raises(TTSEngineNotAvailableError) as exc_info:
        EngineFactory.create(config)
    assert "piper" in exc_info.value.details["available_engines"]


def test_register_new_engine_extends_factory_without_modifying_it() -> None:
    """Memverifikasi Open/Closed Principle: engine baru bisa ditambah tanpa mengubah EngineFactory."""

    class DummyEngine(PiperEngine):
        pass

    EngineFactory.register("dummy_test_engine", lambda config: DummyEngine(config))
    try:
        config = TTSConfig(engine="dummy_test_engine")
        engine = EngineFactory.create(config)
        assert isinstance(engine, DummyEngine)
    finally:
        # Bersihkan registry agar tidak memengaruhi test lain.
        del EngineFactory._registry["dummy_test_engine"]


# --- V2 Phase 7 — build() & list_registered_names() -----------------------------


def test_espeak_is_registered_alongside_piper() -> None:
    """Engine kedua (eSpeak NG) HARUS terdaftar di EngineFactory, tanpa mengubah registrasi Piper."""
    registered = EngineFactory.list_registered_names()
    assert "piper" in registered
    assert "espeak" in registered


def test_styletts2_is_registered_alongside_piper_and_espeak() -> None:
    """Engine ketiga (StyleTTS2, Phase 12) HARUS terdaftar tanpa mengubah registrasi dua engine sebelumnya."""
    registered = EngineFactory.list_registered_names()
    assert "piper" in registered
    assert "espeak" in registered
    assert "styletts2" in registered


def test_build_creates_engine_by_explicit_name_independent_of_config_engine() -> None:
    """`build(name, config)` HARUS memakai `name` yang diberikan, BUKAN `config.engine` --
    berbeda dari `create()` -- inilah yang dipakai TTSEngineManager untuk engine tambahan."""
    from announcement_server.tts.espeak_engine import EspeakEngine

    config = TTSConfig(engine="piper")  # config.engine sengaja "piper"
    engine = EngineFactory.build("espeak", config)  # tapi kita minta "espeak" secara eksplisit
    assert isinstance(engine, EspeakEngine)


def test_build_unknown_engine_raises_not_available_error() -> None:
    config = TTSConfig(engine="piper")
    with pytest.raises(TTSEngineNotAvailableError) as exc_info:
        EngineFactory.build("engine_yang_tidak_ada", config)
    assert exc_info.value.details["requested_engine"] == "engine_yang_tidak_ada"


def test_create_still_delegates_to_config_engine_unchanged() -> None:
    """Memastikan refactor `create()` -> `build()` tidak mengubah perilaku publik `create()`."""
    config = TTSConfig(engine="piper")
    engine = EngineFactory.create(config)
    assert isinstance(engine, PiperEngine)
