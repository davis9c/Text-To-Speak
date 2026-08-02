"""Test HTTP untuk coexistence Piper + eSpeak NG di GET /tts/engines & /tts/voices (V2 Phase 7).

Memakai TTSConfig dengan `additional_engines=["espeak"]` secara eksplisit --
membuktikan kedua engine muncul otomatis di endpoint tanpa perubahan kode
router sama sekali (router tidak tahu nama engine spesifik apa pun).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from announcement_server.api.deps import get_tts_service, get_voice_registry
from announcement_server.core.config import TTSConfig, get_settings
from announcement_server.main import create_app
from announcement_server.tts.service import TTSService
from announcement_server.tts.voice_registry import VoiceRegistry


@pytest.fixture()
def tts_service_with_two_engines() -> TTSService:
    """`espeak_binary_path` sengaja dibiarkan default ("espeak-ng", kemungkinan besar tidak
    terinstal di lingkungan test) -- membuktikan engine tetap MUNCUL di TTSEngineManager
    (konstruksi tidak pernah gagal, graceful degradation sama seperti Piper), voice discovery-nya
    saja yang mengembalikan list kosong karena binary tidak ada (lihat EspeakEngine.list_voices())."""
    return TTSService(TTSConfig(engine="piper", additional_engines=["espeak"]))


@pytest.fixture()
async def voice_registry_with_two_engines(tts_service_with_two_engines: TTSService) -> VoiceRegistry:
    return await VoiceRegistry.create(tts_service_with_two_engines.engine_manager)


@pytest.fixture()
def client(tts_service_with_two_engines: TTSService, voice_registry_with_two_engines: VoiceRegistry) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_tts_service] = lambda: tts_service_with_two_engines
    app.dependency_overrides[get_voice_registry] = lambda: voice_registry_with_two_engines
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_both_engines_appear_automatically_at_engines_endpoint(client: TestClient) -> None:
    """Router TIDAK PERNAH menyebut 'piper'/'espeak' secara eksplisit -- keduanya muncul
    murni karena terdaftar di TTSEngineManager (pembuktian arsitektur Multi-Engine)."""
    response = client.get("/tts/engines")
    assert response.status_code == 200
    body = response.json()

    engine_ids = {engine["id"] for engine in body["engines"]}
    assert engine_ids == {"piper", "espeak"}
    assert body["default_engine"] == "piper"

    engines_by_id = {engine["id"]: engine for engine in body["engines"]}
    assert engines_by_id["piper"]["is_default"] is True
    assert engines_by_id["espeak"]["is_default"] is False


def test_engine_capability_differs_between_piper_and_espeak(client: TestClient) -> None:
    """Bukti nyata arsitektur Capability bekerja: dua engine, dua kapabilitas berbeda,
    diambil lewat kontrak TTSEngine.get_capability() yang sama untuk keduanya."""
    response = client.get("/tts/engines")
    engines_by_id = {engine["id"]: engine for engine in response.json()["engines"]}

    # Piper: tidak punya mekanisme native untuk pitch/volume (lihat PiperEngine.get_capability()).
    assert engines_by_id["piper"]["capability"]["supports_native_pitch"] is False
    assert engines_by_id["piper"]["capability"]["supports_native_volume"] is False

    # eSpeak NG: SECARA NATIVE mendukung keduanya lewat CLI (-p / -a).
    assert engines_by_id["espeak"]["capability"]["supports_native_pitch"] is True
    assert engines_by_id["espeak"]["capability"]["supports_native_volume"] is True

    # Keduanya sama-sama offline (tidak butuh layanan cloud) -- kesamaan yang memang diharapkan.
    assert engines_by_id["piper"]["capability"]["offline"] is True
    assert engines_by_id["espeak"]["capability"]["offline"] is True


def test_voice_registry_endpoint_can_be_filtered_per_engine_even_when_espeak_has_no_voices(
    client: TestClient,
) -> None:
    """`espeak-ng` (binary default) kemungkinan tidak terinstal di lingkungan test -- endpoint
    HARUS tetap merespons 200 dengan voices kosong untuk 'espeak' (bukan error), karena 'espeak'
    tetap dikenal sebagai engine yang valid oleh TTSEngineManager."""
    response = client.get("/tts/voices/espeak")
    assert response.status_code == 200
    assert response.json() == {"voices": [], "count": 0}


def test_unknown_engine_still_returns_503_when_two_engines_active(client: TestClient) -> None:
    response = client.get("/tts/voices/engine_yang_benar_benar_tidak_ada")
    assert response.status_code == 503


# --- Backward compatibility ------------------------------------------------------


def test_speak_endpoint_still_works_identically_with_two_engines_active(client: TestClient) -> None:
    """Request V1 lama (tanpa `engine`) HARUS tetap memakai Piper sebagai default,
    tidak terpengaruh oleh keberadaan eSpeak NG sebagai engine tambahan."""
    response = client.post("/speak", json={"text": "Halo dunia", "voice": "en_US-lessac-medium"})
    assert response.status_code == 201
    body = response.json()
    assert body["engine"] is None  # tidak diminta eksplisit -> null, dipilihkan default (Piper) saat diproses
    assert body["status"] == "pending"


def test_speak_endpoint_accepts_explicit_espeak_engine_selection(client: TestClient) -> None:
    """Satu-satunya perubahan yang dibutuhkan client untuk memakai engine baru: memilih `engine`."""
    response = client.post("/speak", json={"text": "Halo dunia", "voice": "en-us", "engine": "espeak"})
    assert response.status_code == 201
    assert response.json()["engine"] == "espeak"
