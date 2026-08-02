"""Router: TTS Engine & Voice Discovery (V2 Phase 5).

Mengekspos `TTSEngineManager` (engine yang tersedia) dan `VoiceRegistry`
(voice per-engine) sebagai REST API publik. Router ini SENGAJA tidak pernah
menyentuh filesystem atau detail implementasi engine tertentu (mis. Piper)
secara langsung -- seluruh data berasal dari kedua komponen generic
tersebut, sehingga menambah engine baru di masa depan otomatis muncul di
sini tanpa perubahan kode router sama sekali.

Endpoint di sini adalah discovery MURNI (read-only) -- TIDAK memvalidasi
atau memengaruhi pipeline sintesis TTS (`POST /speak` dkk). Validasi voice
saat sintesis tetap sepenuhnya ditangani oleh engine masing-masing, persis
seperti V1 (lihat `tts/service.py`).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from announcement_server.api.deps import TTSServiceDep, VoiceRegistryDep
from announcement_server.core.exceptions import TTSEngineNotAvailableError, VoiceNotFoundError
from announcement_server.schemas.tts import EngineInfo, EngineListResponse, VoiceInfo, VoiceListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tts", tags=["TTS Discovery"])


def _require_known_engine(engine: str, tts_service: TTSServiceDep) -> None:
    """Melempar TTSEngineNotAvailableError (exception project yang sudah ada, 503)
    jika `engine` tidak terdaftar di TTSEngineManager -- dipakai bersama oleh
    endpoint voice per-engine di bawah agar konsisten."""
    available_engines = tts_service.engine_manager.list_engine_names()
    if engine not in available_engines:
        raise TTSEngineNotAvailableError(
            f"Engine TTS '{engine}' tidak tersedia pada server ini.",
            details={"requested_engine": engine, "available_engines": available_engines},
        )


@router.get(
    "/engines",
    response_model=EngineListResponse,
    summary="Daftar TTS engine yang tersedia",
    description="Mengembalikan seluruh TTS engine yang terdaftar di server ini beserta engine default. "
    "Sumber data: TTSEngineManager -- engine baru yang diregistrasikan di masa depan otomatis muncul di sini.",
)
async def list_engines(tts_service: TTSServiceDep) -> EngineListResponse:
    engine_manager = tts_service.engine_manager
    engines = [
        EngineInfo(
            id=name,
            display_name=name.replace("_", " ").replace("-", " ").title(),
            is_default=(name == engine_manager.default_engine_name),
            # Engine yang tersimpan di TTSEngineManager sudah berhasil diinisialisasi
            # (lihat TTSEngineManager.__init__) -- karena itu selalu `available=True`
            # di sini. Kesehatan runtime (mis. binary Piper/eSpeak NG hilang) baru
            # terdeteksi saat sintesis benar-benar dijalankan, bukan lewat endpoint
            # discovery ini.
            available=True,
            # get_capability() adalah method generic milik kontrak TTSEngine (V2 Phase 7)
            # -- router tidak perlu tahu engine mana yang sedang ditanyakan.
            capability=await engine_manager.get(name).get_capability(),
        )
        for name in engine_manager.list_engine_names()
    ]
    return EngineListResponse(engines=engines, default_engine=engine_manager.default_engine_name)


@router.get(
    "/voices",
    response_model=VoiceListResponse,
    summary="Daftar seluruh voice dari seluruh engine",
    description="Mengembalikan seluruh voice yang ditemukan VoiceRegistry, lintas seluruh engine yang terdaftar. "
    "Registry kosong (mis. belum ada voice model Piper terpasang) menghasilkan `voices: []`, bukan error.",
)
async def list_all_voices(voice_registry: VoiceRegistryDep) -> VoiceListResponse:
    voices = [VoiceInfo.from_voice_profile(profile) for profile in voice_registry.list_all()]
    return VoiceListResponse(voices=voices, count=len(voices))


@router.get(
    "/voices/{engine}",
    response_model=VoiceListResponse,
    summary="Daftar voice milik satu engine",
    description="Mengembalikan seluruh voice milik `engine` tertentu. Engine yang tidak terdaftar "
    "menghasilkan error 503 (TTSEngineNotAvailableError) -- bukan daftar kosong -- agar client bisa "
    "membedakan 'engine tidak dikenal' dari 'engine dikenal tapi belum ada voice'.",
)
async def list_voices_by_engine(engine: str, tts_service: TTSServiceDep, voice_registry: VoiceRegistryDep) -> VoiceListResponse:
    _require_known_engine(engine, tts_service)
    voices = [VoiceInfo.from_voice_profile(profile) for profile in voice_registry.list_by_engine(engine)]
    return VoiceListResponse(voices=voices, count=len(voices))


@router.get(
    "/voices/{engine}/{voice_id}",
    response_model=VoiceInfo,
    summary="Detail satu voice",
    description="Mengembalikan detail satu voice berdasarkan engine + id. Mengembalikan error 503 jika "
    "`engine` tidak dikenal, atau 404 (VoiceNotFoundError) jika `voice_id` tidak ditemukan pada engine tersebut.",
)
async def get_voice_detail(
    engine: str, voice_id: str, tts_service: TTSServiceDep, voice_registry: VoiceRegistryDep
) -> VoiceInfo:
    _require_known_engine(engine, tts_service)
    voice = voice_registry.get(engine, voice_id)
    if voice is None:
        raise VoiceNotFoundError(
            f"Voice '{voice_id}' tidak ditemukan pada engine '{engine}'.",
            details={
                "engine": engine,
                "requested_voice": voice_id,
                "available_voices": [v.id for v in voice_registry.list_by_engine(engine)],
            },
        )
    return VoiceInfo.from_voice_profile(voice)
