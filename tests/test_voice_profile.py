"""Unit test untuk model VoiceProfile (V2 Phase 4)."""

from __future__ import annotations

from announcement_server.tts.voice_profile import VoiceProfile


def test_voice_profile_defaults_language_and_gender_to_none() -> None:
    """Field yang tidak diketahui HARUS default None, bukan nilai tebakan apa pun."""
    voice = VoiceProfile(id="v1", engine="piper", name="v1", source="path/to/v1.onnx")
    assert voice.language is None
    assert voice.gender is None
    assert voice.metadata == {}
    assert voice.available is True


def test_voice_profile_registry_key_combines_engine_and_id() -> None:
    voice = VoiceProfile(id="en_US-lessac-medium", engine="piper", name="en_US-lessac-medium", source="x.onnx")
    assert voice.registry_key == ("piper", "en_US-lessac-medium")


def test_voice_profile_same_id_different_engine_have_different_registry_key() -> None:
    """Dua engine berbeda boleh punya voice dengan id yang sama tanpa saling bertabrakan."""
    voice_a = VoiceProfile(id="default", engine="piper", name="default", source="a")
    voice_b = VoiceProfile(id="default", engine="future_engine", name="default", source="b")
    assert voice_a.registry_key != voice_b.registry_key
