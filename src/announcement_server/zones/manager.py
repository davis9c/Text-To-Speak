"""Zone Manager (Phase 6 — Multi Zone).

Mengorkestrasi siklus hidup banyak Zone (jalur audio independen). Setiap
Zone yang dibuat lewat ``create_zone`` mendapat instance-nya SENDIRI dari
komponen yang sudah ada sejak fase sebelumnya (``QueueManager``,
``QueueWorker``, ``PlaybackManager``, ``TTSQueueProcessor``,
``AnnouncementPipelineProcessor``) — kelas-kelas tsb TIDAK diubah atau
diduplikasi, hanya diinstansiasi ulang per zone (persis pola yang sudah
dipakai untuk zone "main" sejak Phase 5, lihat ``main.py``).

Komponen yang SENGAJA DI-SHARE lintas zone (bukan dibuat ulang per zone):

- ``AudioDeviceManager`` — murni enumerasi device (stateless terhadap zone
  mana pun), satu instance cukup untuk seluruh server.
- ``TTSService`` — membungkus engine TTS (mis. proses Piper) + cache audio
  berbasis SHA256 yang independen dari konsep zone; membuatnya per-zone
  hanya akan menggandakan cache & menyia-nyiakan resource tanpa manfaat.

--------------------------------------------------------------------------
Keputusan desain — lock tunggal (``asyncio.Lock``) untuk operasi CRUD zone:

Sama seperti ``QueueManager`` (Phase 2), lock hanya melindungi mutasi
*registry* zone (dict nama -> runtime), BUKAN dipegang selama operasi
awaiting yang berpotensi lama (mis. ``QueueWorker.stop()`` menunggu task
di-cancel). Pola: pop/ambil referensi di dalam lock, lakukan awaiting di
luar lock.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from announcement_server.core.exceptions import (
    ValidationAppError,
    ZoneAlreadyExistsError,
    ZoneNotFoundError,
    ZoneProtectedError,
)
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.playback.manager import PlaybackManager
from announcement_server.playback.models import PlaybackState
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.pipeline_processor import AnnouncementPipelineProcessor
from announcement_server.queueing.tts_processor import TTSQueueProcessor
from announcement_server.queueing.worker import QueueWorker
from announcement_server.tts.service import TTSService
from announcement_server.zones.models import MAIN_ZONE_NAME, ZONE_NAME_PATTERN, Zone

logger = logging.getLogger(__name__)

# Sentinel untuk membedakan "field tidak diberikan sama sekali" (pertahankan
# nilai lama) dari "field diberikan bernilai None/0" pada `update_zone`.
_UNSET = object()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_zone_name(name: str) -> None:
    if not ZONE_NAME_PATTERN.match(name):
        raise ValidationAppError(
            "Nama zone hanya boleh berisi huruf, angka, underscore, dan dash (1-50 karakter).",
            details={"name": name},
        )


@dataclass
class _ZoneRuntime:
    """Kumpulan objek runtime (bukan metadata) milik satu Zone. Privat terhadap modul ini."""

    metadata: Zone
    queue_manager: QueueManager
    playback_manager: PlaybackManager | None
    queue_worker: QueueWorker
    pipeline: AnnouncementPipelineProcessor


class ZoneManager:
    """Mengelola pembuatan, pembaruan, penghapusan, dan lookup Zone."""

    def __init__(
        self,
        *,
        audio_device_manager: AudioDeviceManager | None,
        tts_service: TTSService,
        default_max_size: int = 100,
        default_max_history: int = 1000,
        default_post_playback_delay_seconds: float = 0.5,
    ) -> None:
        self._audio_device_manager = audio_device_manager
        self._tts_service = tts_service
        self._default_max_size = default_max_size
        self._default_max_history = default_max_history
        self._default_post_playback_delay_seconds = default_post_playback_delay_seconds
        self._zones: dict[str, _ZoneRuntime] = {}
        self._lock = asyncio.Lock()

    # --- CRUD --------------------------------------------------------------

    async def create_zone(
        self,
        name: str,
        *,
        device_id: int | None = None,
        volume: float = 1.0,
        enabled: bool = True,
        max_size: int | None = None,
        max_history: int | None = None,
        post_playback_delay_seconds: float | None = None,
    ) -> Zone:
        """Membuat zone baru lengkap dengan Queue, Worker, dan Playback miliknya sendiri.

        Jika ``enabled=True``, ``QueueWorker`` zone ini langsung dimulai
        (idempotent & aman, mengikuti kontrak ``QueueWorker.start()`` sejak
        Phase 2). ``playback_manager`` SELALU dibuat (bila sistem audio
        tersedia) terlepas dari ``enabled`` — status enabled murni
        mengendalikan apakah worker berjalan, bukan apakah zone punya
        kapabilitas playback (lihat docstring modul untuk rationale ini,
        dipertahankan supaya toggle enable/disable lewat ``update_zone``
        tidak perlu membongkar-pasang pipeline).
        """
        _validate_zone_name(name)
        async with self._lock:
            if name in self._zones:
                raise ZoneAlreadyExistsError(f"Zone '{name}' sudah ada.", details={"name": name})

            queue_manager = QueueManager(
                max_size=max_size if max_size is not None else self._default_max_size,
                max_history=max_history if max_history is not None else self._default_max_history,
            )

            playback_manager: PlaybackManager | None = None
            if self._audio_device_manager is not None:
                playback_manager = PlaybackManager(self._audio_device_manager)
                if device_id is not None:
                    try:
                        playback_manager.select_device(device_id)
                    except Exception:
                        logger.warning(
                            "Zone '%s': gagal memilih device_id=%s, memakai default output device sistem.",
                            name,
                            device_id,
                            exc_info=True,
                        )

            tts_processor = TTSQueueProcessor(self._tts_service, queue_manager)
            pipeline = AnnouncementPipelineProcessor(
                tts_processor,
                queue_manager,
                playback_manager,
                post_playback_delay_seconds=(
                    post_playback_delay_seconds
                    if post_playback_delay_seconds is not None
                    else self._default_post_playback_delay_seconds
                ),
                volume_gain=volume,
                scaled_audio_dir=f"cache/zone_audio/{name}",
            )
            queue_worker = QueueWorker(queue_manager, item_processor=pipeline)
            if enabled:
                queue_worker.start()

            now = _utcnow()
            metadata = Zone(
                name=name,
                enabled=enabled,
                device_id=device_id,
                volume=volume,
                created_at=now,
                updated_at=now,
            )
            self._zones[name] = _ZoneRuntime(
                metadata=metadata,
                queue_manager=queue_manager,
                playback_manager=playback_manager,
                queue_worker=queue_worker,
                pipeline=pipeline,
            )
            logger.info(
                "Zone dibuat: name=%s enabled=%s device_id=%s volume=%s", name, enabled, device_id, volume
            )
            return metadata.model_copy()

    async def update_zone(
        self,
        name: str,
        *,
        device_id: int | None = _UNSET,  # type: ignore[assignment]
        volume: float = _UNSET,  # type: ignore[assignment]
        enabled: bool = _UNSET,  # type: ignore[assignment]
    ) -> Zone:
        """Memperbarui sebagian atau seluruh atribut zone (device/volume/enabled).

        Parameter yang tidak diberikan (default ``_UNSET``) TIDAK diubah,
        sehingga ``PUT /zones/{name}`` mendukung pembaruan parsial.
        """
        runtime = self._zones.get(name)
        if runtime is None:
            raise ZoneNotFoundError(f"Zone '{name}' tidak ditemukan.", details={"name": name})

        if device_id is not _UNSET:
            if runtime.playback_manager is not None and device_id is not None:
                # Melempar AudioDeviceNotFoundError jika device_id tidak valid — dibiarkan
                # menjalar (ditangani oleh global exception handler, sama seperti POST /device).
                runtime.playback_manager.select_device(device_id)
            runtime.metadata.device_id = device_id

        if volume is not _UNSET:
            runtime.pipeline.volume_gain = volume
            runtime.metadata.volume = volume

        if enabled is not _UNSET and enabled != runtime.metadata.enabled:
            if enabled:
                runtime.queue_worker.start()
            else:
                await runtime.queue_worker.stop()
            runtime.metadata.enabled = enabled

        runtime.metadata.updated_at = _utcnow()
        logger.info(
            "Zone diperbarui: name=%s enabled=%s device_id=%s volume=%s",
            name,
            runtime.metadata.enabled,
            runtime.metadata.device_id,
            runtime.metadata.volume,
        )
        return runtime.metadata.model_copy()

    async def delete_zone(self, name: str) -> None:
        """Menghapus zone beserta seluruh runtime-nya (worker dihentikan graceful).

        Zone ``main`` dilindungi (lihat ``ZoneProtectedError``) karena
        dipakai oleh seluruh endpoint Phase 1-5 demi backward compatibility.
        """
        if name == MAIN_ZONE_NAME:
            raise ZoneProtectedError(
                "Zone 'main' tidak dapat dihapus karena dipakai oleh endpoint /speak, /queue, /devices, dst.",
                details={"name": name},
            )
        async with self._lock:
            runtime = self._zones.pop(name, None)
        if runtime is None:
            raise ZoneNotFoundError(f"Zone '{name}' tidak ditemukan.", details={"name": name})

        await runtime.queue_worker.stop()
        if runtime.playback_manager is not None:
            await runtime.playback_manager.stop()
        logger.info("Zone dihapus: name=%s", name)

    # --- Lookup --------------------------------------------------------------

    def get_zone(self, name: str) -> Zone:
        runtime = self._zones.get(name)
        if runtime is None:
            raise ZoneNotFoundError(f"Zone '{name}' tidak ditemukan.", details={"name": name})
        return runtime.metadata.model_copy()

    def list_zones(self) -> list[Zone]:
        return [runtime.metadata.model_copy() for runtime in self._zones.values()]

    def get_queue_manager(self, name: str) -> QueueManager:
        return self._get_runtime(name).queue_manager

    def get_playback_manager(self, name: str) -> PlaybackManager | None:
        """Mengembalikan ``None`` jika sistem audio (PortAudio/driver) tidak tersedia di server ini."""
        return self._get_runtime(name).playback_manager

    def get_queue_worker(self, name: str) -> QueueWorker:
        return self._get_runtime(name).queue_worker

    def is_worker_running(self, name: str) -> bool:
        return self._get_runtime(name).queue_worker.is_running

    def get_playback_state(self, name: str) -> PlaybackState | None:
        playback_manager = self._get_runtime(name).playback_manager
        return playback_manager.state if playback_manager is not None else None

    def _get_runtime(self, name: str) -> _ZoneRuntime:
        runtime = self._zones.get(name)
        if runtime is None:
            raise ZoneNotFoundError(f"Zone '{name}' tidak ditemukan.", details={"name": name})
        return runtime

    # --- Lifecycle --------------------------------------------------------------

    async def shutdown(self) -> None:
        """Menghentikan seluruh worker & playback pada seluruh zone secara graceful.

        Dipanggil sekali saat aplikasi shutdown (lihat ``main.py`` lifespan).
        """
        async with self._lock:
            runtimes = list(self._zones.values())
        for runtime in runtimes:
            if runtime.playback_manager is not None:
                await runtime.playback_manager.stop()
            await runtime.queue_worker.stop()
        logger.info("Seluruh zone (%d) dihentikan.", len(runtimes))
