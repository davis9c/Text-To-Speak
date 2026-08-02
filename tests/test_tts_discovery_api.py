"""Test HTTP untuk V2 Phase 5 — GET /tts/engines, /tts/voices, /tts/voices/{engine}, /tts/voices/{engine}/{voice_id}."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.api.deps import get_tts_service, get_voice_registry
from announcement_server.core.config import TTSConfig, get_settings
from announcement_server.main import create_app
from announcement_server.tts.service import TTSService
from announcement_server.tts.voice_registry import VoiceRegistry


@pytest.fixture()
def voice_models_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "voice_models"
    directory.mkdir()
    (directory / "voice_a.onnx").write_bytes(b"dummy")
    (directory / "voice_a.onnx.json").write_text(json.dumps({"language": {"code": "en_US"}}))
    # voice_b SENGAJA tanpa .onnx.json pasangannya -> harus muncul dengan available=False.
    (directory / "voice_b.onnx").write_bytes(b"dummy")
    return directory


@pytest.fixture()
def tts_service(voice_models_dir: Path) -> TTSService:
    return TTSService(
        TTSConfig(engine="piper", piper_binary_path="/tidak/ada/piper_binary", piper_models_dir=str(voice_models_dir))
    )


@pytest.fixture()
async def voice_registry(tts_service: TTSService) -> VoiceRegistry:
    return await VoiceRegistry.create(tts_service.engine_manager)


@pytest.fixture()
def client(tts_service: TTSService, voice_registry: VoiceRegistry) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_tts_service] = lambda: tts_service
    app.dependency_overrides[get_voice_registry] = lambda: voice_registry
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


# --- GET /tts/engines --------------------------------------------------------


def test_list_engines_includes_piper_as_default(client: TestClient) -> None:
    response = client.get("/tts/engines")
    assert response.status_code == 200
    body = response.json()
    assert body["default_engine"] == "piper"
    piper_entries = [engine for engine in body["engines"] if engine["id"] == "piper"]
    assert len(piper_entries) == 1
    assert piper_entries[0]["is_default"] is True
    assert piper_entries[0]["available"] is True


def test_list_engines_does_not_expose_internal_paths(client: TestClient) -> None:
    """Response engine TIDAK BOLEH menyertakan path binary/model atau detail config server."""
    response = client.get("/tts/engines")
    body_text = response.text
    assert "piper_binary_path" not in body_text
    assert "piper_models_dir" not in body_text
    assert "tidak_ada_piper_binary" not in body_text  # nilai path fixture di atas


# --- GET /tts/voices ----------------------------------------------------------


def test_list_all_voices_returns_voices_from_registry(client: TestClient) -> None:
    response = client.get("/tts/voices")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    voices_by_id = {voice["id"]: voice for voice in body["voices"]}
    assert voices_by_id["voice_a"]["available"] is True
    assert voices_by_id["voice_a"]["language"] == "en_US"
    assert voices_by_id["voice_b"]["available"] is False


def test_voice_response_does_not_expose_internal_source_path(client: TestClient) -> None:
    """VoiceInfo TIDAK BOLEH menyertakan field `source` (path file model) milik VoiceProfile internal."""
    response = client.get("/tts/voices")
    body = response.json()
    for voice in body["voices"]:
        assert "source" not in voice


def test_list_all_voices_empty_registry_returns_empty_list_not_error(tmp_path: Path) -> None:
    """Registry kosong (mis. belum ada voice model terpasang) HARUS mengembalikan `voices: []`, bukan error."""
    empty_service = TTSService(
        TTSConfig(engine="piper", piper_binary_path="/tidak/ada", piper_models_dir=str(tmp_path / "kosong"))
    )
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_tts_service] = lambda: empty_service
    app.dependency_overrides[get_voice_registry] = lambda: VoiceRegistry()  # belum di-refresh sama sekali
    with TestClient(app) as test_client:
        response = test_client.get("/tts/voices")
        assert response.status_code == 200
        assert response.json() == {"voices": [], "count": 0}
    app.dependency_overrides.clear()
    get_settings.cache_clear()


# --- GET /tts/voices/{engine} --------------------------------------------------


def test_list_voices_by_known_engine_returns_only_that_engine(client: TestClient) -> None:
    response = client.get("/tts/voices/piper")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert all(voice["engine"] == "piper" for voice in body["voices"])


def test_list_voices_by_unknown_engine_returns_503_engine_not_available(client: TestClient) -> None:
    response = client.get("/tts/voices/engine_yang_tidak_ada")
    assert response.status_code == 503
    body = response.json()
    assert "engine_yang_tidak_ada" in json.dumps(body)


# --- GET /tts/voices/{engine}/{voice_id} ---------------------------------------


def test_get_voice_detail_success(client: TestClient) -> None:
    response = client.get("/tts/voices/piper/voice_a")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "voice_a"
    assert body["engine"] == "piper"
    assert body["language"] == "en_US"
    assert body["available"] is True


def test_get_voice_detail_unavailable_voice_still_returned_not_404(client: TestClient) -> None:
    """voice_b terdaftar (walau available=False) -- HARUS tetap bisa diambil detailnya, bukan 404."""
    response = client.get("/tts/voices/piper/voice_b")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_get_voice_detail_voice_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/tts/voices/piper/voice_tidak_ada")
    assert response.status_code == 404


def test_get_voice_detail_unknown_engine_returns_503(client: TestClient) -> None:
    response = client.get("/tts/voices/engine_yang_tidak_ada/voice_a")
    assert response.status_code == 503


# --- OpenAPI documentation ------------------------------------------------------


def test_new_endpoints_appear_in_openapi_schema(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/tts/engines" in paths
    assert "/tts/voices" in paths
    assert "/tts/voices/{engine}" in paths
    assert "/tts/voices/{engine}/{voice_id}" in paths
    for path in ("/tts/engines", "/tts/voices", "/tts/voices/{engine}", "/tts/voices/{engine}/{voice_id}"):
        get_spec = paths[path]["get"]
        assert get_spec.get("summary")
        assert get_spec.get("description")
        assert get_spec.get("responses", {}).get("200", {}).get("content")


# --- Backward compatibility ------------------------------------------------------


def test_speak_endpoint_unaffected_by_voice_discovery_endpoints(client: TestClient) -> None:
    """Endpoint lama (POST /speak) HARUS tetap bekerja identik, tidak terpengaruh sama sekali
    oleh keberadaan VoiceRegistry/router /tts/* baru."""
    response = client.post("/speak", json={"text": "Halo dunia", "voice": "voice_a"})
    assert response.status_code == 201
    body = response.json()
    assert body["text"] == "Halo dunia"
    assert body["voice"] == "voice_a"
    assert body["status"] == "pending"
