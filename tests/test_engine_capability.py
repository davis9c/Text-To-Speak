"""Unit test untuk EngineCapability (V2 Phase 7) — menutup celah RC1-6.

Sebelumnya `get_capability()` hanya diuji secara TIDAK LANGSUNG lewat
`test_espeak_engine.py` (satu engine) dan `test_multi_engine_coexistence_api.py`
(level API/JSON). Belum ada test langsung untuk:
  - default `EngineCapability` itu sendiri (baseline konservatif),
  - default `TTSEngine.get_capability()` di base class (dipakai FakeEngine
    manapun yang tidak meng-override-nya -- 11 file test lain di suite ini),
  - `PiperEngine.get_capability()` secara unit (bukan lewat HTTP response).
"""

from __future__ import annotations

from announcement_server.core.config import TTSConfig
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_capability import EngineCapability
from announcement_server.tts.piper_engine import PiperEngine


def test_engine_capability_default_is_conservative_baseline() -> None:
    """Default `EngineCapability()` HARUS berupa baseline paling konservatif:
    hanya `supports_speed` True (karena seluruh engine yang ada di project ini
    sejauh ini punya kontrol speed), sisanya False/None -- TIDAK PERNAH
    berasumsi kapabilitas native yang belum tentu dimiliki suatu engine."""
    capability = EngineCapability()

    assert capability.supports_speed is True
    assert capability.supports_native_pitch is False
    assert capability.supports_native_volume is False
    assert capability.supports_ssml is False
    assert capability.offline is True
    assert capability.max_text_length is None
    assert capability.native_sample_rate is None


class _MinimalFakeEngine(TTSEngine):
    """Engine palsu yang SENGAJA tidak meng-override `get_capability()` sama sekali --
    merepresentasikan pola yang dipakai puluhan FakeEngine lain di seluruh test suite."""

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:  # pragma: no cover - tak dipakai
        return b""


async def test_tts_engine_base_default_get_capability_matches_conservative_baseline() -> None:
    """Engine yang tidak meng-override `get_capability()` (mis. FakeEngine test-double manapun
    di suite ini) HARUS tetap mengembalikan baseline konservatif yang sama, BUKAN error atau
    NotImplementedError -- inilah yang membuat penambahan kontrak ini di Phase 7 non-breaking."""
    engine = _MinimalFakeEngine()
    capability = await engine.get_capability()
    assert capability == EngineCapability()


async def test_piper_engine_capability_has_no_native_pitch_or_volume() -> None:
    """Unit test LANGSUNG (bukan lewat HTTP) untuk PiperEngine.get_capability() --
    sebelumnya hanya diverifikasi secara tidak langsung lewat response JSON API."""
    config = TTSConfig(engine="piper", piper_binary_path="/tidak/dipakai/di/test/ini")
    engine = PiperEngine(config)
    capability = await engine.get_capability()

    assert capability.supports_speed is True
    assert capability.supports_native_pitch is False  # CLI Piper tidak punya flag pitch
    assert capability.supports_native_volume is False  # CLI Piper tidak punya flag volume
    assert capability.supports_ssml is False
    assert capability.offline is True
    assert capability.max_text_length is None
    assert capability.native_sample_rate is None


async def test_get_capability_never_touches_filesystem_or_subprocess() -> None:
    """`get_capability()` bersifat murni informasional (nilai statis) -- HARUS bisa dipanggil
    tanpa binary/model apa pun tersedia, tidak boleh melempar error terkait ketidaktersediaan
    engine (berbeda dari `synthesize()`/`list_voices()` yang memang butuh binary nyata)."""
    config = TTSConfig(engine="piper", piper_binary_path="/path/yang/pasti/tidak/ada")
    engine = PiperEngine(config)
    capability = await engine.get_capability()  # TIDAK BOLEH raise apa pun
    assert isinstance(capability, EngineCapability)
