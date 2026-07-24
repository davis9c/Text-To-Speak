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
