"""Unit test untuk VoiceRegistry (V2 Phase 4).

Memakai FakeEngine (bukan Piper asli) agar test murni memverifikasi logic
VoiceRegistry itu sendiri (refresh, lookup, validasi, grouping per-engine),
sepenuhnya independen dari implementasi engine tertentu -- membuktikan
registry benar-benar generic/engine-agnostic.
"""

from __future__ import annotations

from announcement_server.core.config import TTSConfig
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.engine_manager import TTSEngineManager
from announcement_server.tts.voice_profile import VoiceProfile
from announcement_server.tts.voice_registry import VoiceRegistry


class _FakeEngineWithVoices(TTSEngine):
    """Test double yang menyediakan voice tetap, tanpa I/O apa pun."""

    def __init__(self, config: TTSConfig) -> None:
        self._engine_name = config.engine

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:  # pragma: no cover - tak dipakai
        return b""

    async def list_voices(self) -> list[VoiceProfile]:
        return [
            VoiceProfile(id="voice_a", engine=self._engine_name, name="Voice A", source="fake_a"),
            VoiceProfile(id="voice_b", engine=self._engine_name, name="Voice B", source="fake_b", available=False),
        ]


def _register_fake_engine(name: str) -> None:
    EngineFactory.register(name, _FakeEngineWithVoices)


async def test_refresh_populates_voices_from_engine() -> None:
    _register_fake_engine("fake_registry_engine_1")
    try:
        manager = TTSEngineManager(TTSConfig(engine="fake_registry_engine_1"))
        registry = VoiceRegistry()
        await registry.refresh(manager)

        all_voices = registry.list_all()
        assert {voice.id for voice in all_voices} == {"voice_a", "voice_b"}
        assert all(voice.engine == "fake_registry_engine_1" for voice in all_voices)
    finally:
        del EngineFactory._registry["fake_registry_engine_1"]


async def test_create_factory_refreshes_immediately() -> None:
    _register_fake_engine("fake_registry_engine_2")
    try:
        manager = TTSEngineManager(TTSConfig(engine="fake_registry_engine_2"))
        registry = await VoiceRegistry.create(manager)
        assert len(registry.list_all()) == 2
    finally:
        del EngineFactory._registry["fake_registry_engine_2"]


async def test_get_returns_voice_by_engine_and_id() -> None:
    _register_fake_engine("fake_registry_engine_3")
    try:
        manager = TTSEngineManager(TTSConfig(engine="fake_registry_engine_3"))
        registry = await VoiceRegistry.create(manager)

        found = registry.get("fake_registry_engine_3", "voice_a")
        assert found is not None
        assert found.id == "voice_a"

        assert registry.get("fake_registry_engine_3", "voice_tidak_ada") is None
        assert registry.get("engine_lain", "voice_a") is None  # engine salah -> tidak ditemukan
    finally:
        del EngineFactory._registry["fake_registry_engine_3"]


async def test_is_valid_true_only_for_available_registered_voice() -> None:
    _register_fake_engine("fake_registry_engine_4")
    try:
        manager = TTSEngineManager(TTSConfig(engine="fake_registry_engine_4"))
        registry = await VoiceRegistry.create(manager)

        assert registry.is_valid("fake_registry_engine_4", "voice_a") is True  # available=True
        assert registry.is_valid("fake_registry_engine_4", "voice_b") is False  # available=False
        assert registry.is_valid("fake_registry_engine_4", "voice_tidak_ada") is False  # tidak terdaftar
    finally:
        del EngineFactory._registry["fake_registry_engine_4"]


async def test_list_by_engine_filters_correctly() -> None:
    _register_fake_engine("fake_registry_engine_5")
    try:
        manager = TTSEngineManager(TTSConfig(engine="fake_registry_engine_5"))
        registry = await VoiceRegistry.create(manager)

        assert [voice.id for voice in registry.list_by_engine("fake_registry_engine_5")] == ["voice_a", "voice_b"]
        assert registry.list_by_engine("engine_yang_tidak_ada") == []
    finally:
        del EngineFactory._registry["fake_registry_engine_5"]


async def test_refresh_replaces_previous_state_not_merges() -> None:
    """Voice lama yang sudah tidak dikembalikan engine harus HILANG dari registry setelah refresh,
    bukan tertinggal (mis. karena file model sudah dihapus dari disk)."""

    class _EngineWithMutableVoices(TTSEngine):
        voices: list[VoiceProfile] = []

        async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:  # pragma: no cover
            return b""

        async def list_voices(self) -> list[VoiceProfile]:
            return _EngineWithMutableVoices.voices

    EngineFactory.register("fake_registry_engine_6", _EngineWithMutableVoices)
    try:
        _EngineWithMutableVoices.voices = [
            VoiceProfile(id="will_be_removed", engine="fake_registry_engine_6", name="x", source="x"),
        ]
        manager = TTSEngineManager(TTSConfig(engine="fake_registry_engine_6"))
        registry = await VoiceRegistry.create(manager)
        assert registry.get("fake_registry_engine_6", "will_be_removed") is not None

        _EngineWithMutableVoices.voices = [
            VoiceProfile(id="new_voice", engine="fake_registry_engine_6", name="y", source="y"),
        ]
        await registry.refresh(manager)

        assert registry.get("fake_registry_engine_6", "will_be_removed") is None
        assert registry.get("fake_registry_engine_6", "new_voice") is not None
    finally:
        del EngineFactory._registry["fake_registry_engine_6"]


async def test_registry_does_not_import_piper_specifically() -> None:
    """Audit generic-ness: VoiceRegistry hanya boleh mengimpor kontrak TTSEngine/TTSEngineManager
    generic, TIDAK PERNAH mengimpor `piper_engine` (kata "Piper" boleh muncul di docstring
    sebagai penjelasan, tapi TIDAK BOLEH ada di daftar import modul)."""
    import ast
    import inspect

    from announcement_server.tts import voice_registry as voice_registry_module

    tree = ast.parse(inspect.getsource(voice_registry_module))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    assert not any("piper" in module_name.lower() for module_name in imported_modules), imported_modules
