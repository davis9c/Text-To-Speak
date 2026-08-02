"""Unit test untuk Piper Voice Discovery (V2 Phase 4 — PiperEngine.list_voices()).

Memakai fixture direktori model palsu (bukan Piper asli) untuk memverifikasi
mekanisme scan/pairing `.onnx` + `.onnx.json`, TANPA daftar voice yang
di-hardcode di kode produksi.
"""

from __future__ import annotations

import json
from pathlib import Path

from announcement_server.core.config import TTSConfig
from announcement_server.tts.piper_engine import PiperEngine

REALISTIC_PIPER_VOICE_CONFIG = {
    "audio": {"sample_rate": 22050},
    "num_speakers": 1,
    "language": {
        "code": "en_US",
        "family": "en",
        "region": "US",
        "name_native": "English",
        "name_english": "English",
        "country_english": "United States",
    },
}


def _make_config(models_dir: Path, binary_path: Path | None = None) -> TTSConfig:
    return TTSConfig(
        engine="piper",
        piper_binary_path=str(binary_path) if binary_path else "engines/piper/piper.exe",
        piper_models_dir=str(models_dir),
    )


async def test_list_voices_returns_empty_list_when_models_dir_missing(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "does_not_exist")
    engine = PiperEngine(config)
    assert await engine.list_voices() == []


async def test_list_voices_discovers_pairs_from_disk_not_hardcoded(tmp_path: Path) -> None:
    """Voice yang ditemukan HARUS persis sesuai isi direktori -- mengganti nama file berarti
    mengganti hasil discovery, membuktikan tidak ada daftar hardcoded di kode produksi."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    for voice_name in ("en_US-lessac-medium", "id_ID-example-voice"):
        (models_dir / f"{voice_name}.onnx").write_bytes(b"dummy")
        (models_dir / f"{voice_name}.onnx.json").write_text(json.dumps(REALISTIC_PIPER_VOICE_CONFIG))

    engine = PiperEngine(_make_config(models_dir))
    voices = await engine.list_voices()

    assert {voice.id for voice in voices} == {"en_US-lessac-medium", "id_ID-example-voice"}
    assert all(voice.engine == "piper" for voice in voices)
    assert all(voice.available for voice in voices)


async def test_list_voices_extracts_real_language_code_from_config(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "en_US-lessac-medium.onnx").write_bytes(b"dummy")
    (models_dir / "en_US-lessac-medium.onnx.json").write_text(json.dumps(REALISTIC_PIPER_VOICE_CONFIG))

    engine = PiperEngine(_make_config(models_dir))
    voices = await engine.list_voices()

    assert len(voices) == 1
    voice = voices[0]
    assert voice.language == "en_US"
    assert voice.metadata["sample_rate"] == 22050
    assert voice.metadata["num_speakers"] == 1
    assert voice.metadata["language_name"] == "English"


async def test_list_voices_gender_is_always_none_for_piper(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "voice1.onnx").write_bytes(b"dummy")
    (models_dir / "voice1.onnx.json").write_text(json.dumps(REALISTIC_PIPER_VOICE_CONFIG))

    engine = PiperEngine(_make_config(models_dir))
    voices = await engine.list_voices()
    assert voices[0].gender is None


async def test_list_voices_marks_voice_without_config_json_as_unavailable(tmp_path: Path) -> None:
    """.onnx tanpa .onnx.json pasangannya HARUS tetap muncul di daftar (bukan disembunyikan),
    tetapi ditandai available=False -- konsisten dengan _synthesize_once() yang akan menolaknya
    dengan VoiceNotFoundError jika benar-benar dipakai untuk sintesis."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "incomplete_voice.onnx").write_bytes(b"dummy")
    # Sengaja TIDAK membuat incomplete_voice.onnx.json

    engine = PiperEngine(_make_config(models_dir))
    voices = await engine.list_voices()

    assert len(voices) == 1
    assert voices[0].id == "incomplete_voice"
    assert voices[0].available is False
    assert voices[0].language is None


async def test_list_voices_handles_malformed_json_without_crashing(tmp_path: Path) -> None:
    """Config JSON yang rusak tidak boleh membuat seluruh discovery gagal -- voice lain tetap
    ditemukan, dan voice yang config-nya rusak tetap terdaftar tanpa metadata bahasa."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "broken_voice.onnx").write_bytes(b"dummy")
    (models_dir / "broken_voice.onnx.json").write_text("{ini bukan json yang valid")
    (models_dir / "healthy_voice.onnx").write_bytes(b"dummy")
    (models_dir / "healthy_voice.onnx.json").write_text(json.dumps(REALISTIC_PIPER_VOICE_CONFIG))

    engine = PiperEngine(_make_config(models_dir))
    voices = {voice.id: voice for voice in await engine.list_voices()}

    assert set(voices) == {"broken_voice", "healthy_voice"}
    assert voices["broken_voice"].available is True  # .onnx.json ADA (walau isinya rusak) -> tetap available
    assert voices["broken_voice"].language is None
    assert voices["healthy_voice"].language == "en_US"


async def test_get_voice_uses_default_lookup_from_list_voices(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "target_voice.onnx").write_bytes(b"dummy")
    (models_dir / "target_voice.onnx.json").write_text(json.dumps(REALISTIC_PIPER_VOICE_CONFIG))

    engine = PiperEngine(_make_config(models_dir))

    found = await engine.get_voice("target_voice")
    assert found is not None
    assert found.id == "target_voice"

    not_found = await engine.get_voice("voice_yang_tidak_ada")
    assert not_found is None
