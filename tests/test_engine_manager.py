"""Unit test untuk TTSEngineManager (V2 Phase 2)."""

from __future__ import annotations

import pytest

from announcement_server.core.config import TTSConfig
from announcement_server.core.exceptions import TTSEngineNotAvailableError
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.engine_manager import TTSEngineManager
from announcement_server.tts.piper_engine import PiperEngine


def test_default_engine_name_matches_config_engine() -> None:
    config = TTSConfig(engine="piper")
    manager = TTSEngineManager(config)
    assert manager.default_engine_name == "piper"


def test_get_without_name_returns_default_engine() -> None:
    config = TTSConfig(engine="piper")
    manager = TTSEngineManager(config)
    assert isinstance(manager.get(), PiperEngine)
    assert isinstance(manager.get(None), PiperEngine)


def test_get_with_explicit_default_name_returns_same_instance() -> None:
    config = TTSConfig(engine="piper")
    manager = TTSEngineManager(config)
    assert manager.get("piper") is manager.get()


def test_list_engine_names_contains_default_engine() -> None:
    config = TTSConfig(engine="piper")
    manager = TTSEngineManager(config)
    assert manager.list_engine_names() == ["piper"]


def test_get_unknown_engine_raises_not_available_error_without_fallback() -> None:
    """Engine yang tidak dikenali HARUS melempar error, TIDAK fallback diam-diam ke default."""
    config = TTSConfig(engine="piper")
    manager = TTSEngineManager(config)

    with pytest.raises(TTSEngineNotAvailableError) as exc_info:
        manager.get("engine_yang_tidak_ada")

    assert exc_info.value.details["requested_engine"] == "engine_yang_tidak_ada"
    assert exc_info.value.details["default_engine"] == "piper"
    assert "piper" in exc_info.value.details["available_engines"]
    assert "engine_yang_tidak_ada" not in exc_info.value.details["available_engines"]


class _DummyEngine(PiperEngine):
    """Double sederhana yang mewarisi PiperEngine hanya agar TTSConfig apa adanya bisa dipakai."""


def test_manager_only_activates_configured_engine() -> None:
    """Mendaftarkan engine lain di EngineFactory TIDAK membuatnya otomatis aktif di manager —
    manager hanya membangun engine yang disebut oleh `config.engine` (Piper tetap satu-satunya
    engine aktif sesuai instruksi V2 Phase 2, KECUALI secara eksplisit diaktifkan lewat
    `tts.additional_engines` -- lihat test V2 Phase 7 di bawah)."""
    EngineFactory.register("dummy_inactive_engine", lambda config: _DummyEngine(config))
    try:
        config = TTSConfig(engine="piper")
        manager = TTSEngineManager(config)
        assert manager.list_engine_names() == ["piper"]
        with pytest.raises(TTSEngineNotAvailableError):
            manager.get("dummy_inactive_engine")
    finally:
        del EngineFactory._registry["dummy_inactive_engine"]


# --- V2 Phase 7 — additional_engines (multi-engine coexistence) -----------------


def test_additional_engines_defaults_to_empty_and_is_backward_compatible() -> None:
    """TTSConfig tanpa `additional_engines` HARUS berperilaku identik dengan Phase 2-6."""
    config = TTSConfig(engine="piper")
    assert config.additional_engines == []
    manager = TTSEngineManager(config)
    assert manager.list_engine_names() == ["piper"]


def test_additional_engines_activates_second_engine_alongside_default() -> None:
    """Piper (default) DAN eSpeak NG (tambahan) harus hidup berdampingan di satu manager."""
    config = TTSConfig(engine="piper", additional_engines=["espeak"])
    manager = TTSEngineManager(config)

    assert manager.default_engine_name == "piper"
    assert set(manager.list_engine_names()) == {"piper", "espeak"}

    from announcement_server.tts.espeak_engine import EspeakEngine
    from announcement_server.tts.piper_engine import PiperEngine

    assert isinstance(manager.get("piper"), PiperEngine)
    assert isinstance(manager.get("espeak"), EspeakEngine)
    assert manager.get() is manager.get("piper")  # engine default tidak berubah


def test_additional_engines_activates_three_engines_simultaneously() -> None:
    """Phase 12: Piper + eSpeak NG + StyleTTS2 hidup berdampingan sekaligus, TANPA satu pun
    baris kode TTSEngineManager berubah untuk mengakomodasi engine ketiga -- pembuktian
    langsung bahwa arsitektur Multi-Engine benar-benar generic (bukan hanya untuk 2 engine)."""
    config = TTSConfig(engine="piper", additional_engines=["espeak", "styletts2"])
    manager = TTSEngineManager(config)

    assert manager.default_engine_name == "piper"
    assert set(manager.list_engine_names()) == {"piper", "espeak", "styletts2"}

    from announcement_server.tts.espeak_engine import EspeakEngine
    from announcement_server.tts.piper_engine import PiperEngine
    from announcement_server.tts.styletts2_engine import StyleTTS2Engine

    assert isinstance(manager.get("piper"), PiperEngine)
    assert isinstance(manager.get("espeak"), EspeakEngine)
    assert isinstance(manager.get("styletts2"), StyleTTS2Engine)


def test_additional_engines_with_default_engine_name_does_not_duplicate() -> None:
    """Menyebut nama engine default di dalam `additional_engines` tidak boleh membangunnya dua kali."""
    config = TTSConfig(engine="piper", additional_engines=["piper", "espeak"])
    manager = TTSEngineManager(config)
    assert set(manager.list_engine_names()) == {"piper", "espeak"}


def test_additional_engine_build_failure_is_not_fatal_to_startup() -> None:
    """Jika engine TAMBAHAN gagal dibangun, server (manager) tetap harus berdiri dengan
    engine default tetap aktif -- HANYA engine tambahan yang bermasalah yang dilewati."""

    def _failing_builder(config: TTSConfig) -> "_DummyEngine":  # pragma: no cover - selalu raise sebelum return
        raise RuntimeError("simulasi kegagalan konstruksi engine tambahan")

    EngineFactory.register("failing_additional_engine", _failing_builder)
    try:
        config = TTSConfig(engine="piper", additional_engines=["failing_additional_engine"])
        manager = TTSEngineManager(config)  # TIDAK BOLEH melempar exception

        assert manager.list_engine_names() == ["piper"]  # engine yang gagal tidak masuk
        assert manager.default_engine_name == "piper"
        with pytest.raises(TTSEngineNotAvailableError):
            manager.get("failing_additional_engine")
    finally:
        del EngineFactory._registry["failing_additional_engine"]


def test_default_engine_build_failure_is_still_fatal() -> None:
    """Berbeda dari engine tambahan: kegagalan membangun engine DEFAULT tetap fatal
    (perilaku V1/Phase 2 TIDAK berubah)."""
    with pytest.raises(TTSEngineNotAvailableError):
        TTSEngineManager(TTSConfig(engine="engine_default_yang_tidak_terdaftar"))
