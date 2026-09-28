"""Announcement Pipeline Processor (Phase 5 — Worker).

Menyatukan seluruh tahap pipeline pada roadmap Phase 5::

    Queue -> Cache -> Generate -> Playback -> Delay -> Queue Berikutnya

menjadi satu ``item_processor`` yang disuntikkan ke ``QueueWorker``.
``QueueWorker`` sendiri (Phase 2) **TIDAK diubah sama sekali** — persis
seperti yang sudah direncanakan sejak komentar di ``queueing/worker.py``:
worker hanya butuh objek apa pun yang memenuhi kontrak
``Callable[[QueueItem], Awaitable[None]]``.

Pemetaan tahap roadmap -> implementasi:

1. **Queue**       -> item PENDING di-dequeue oleh ``QueueWorker`` (Phase 2, tidak berubah).
2. **Cache/Generate** -> didelegasikan penuh ke ``TTSQueueProcessor`` (Phase 3,
   tidak diduplikasi di sini — hanya dipanggil sebagai komponen).
3. **Playback**    -> hasil audio (WAV) diputar lewat ``PlaybackManager``
   (Phase 4), lalu menunggu hingga tuntas lewat ``wait_until_finished()``
   (baru ditambahkan pada Phase 5) sebelum lanjut ke tahap berikutnya.
4. **Delay**       -> jeda konfigurasi (``playback.post_playback_delay_seconds``)
   supaya antar-pengumuman TOA tidak bertabrakan/terlalu rapat.
5. **Queue Berikutnya** -> terjadi otomatis: ``QueueWorker._run`` melanjutkan
   loop-nya begitu ``__call__`` di bawah ini selesai/return.

--------------------------------------------------------------------------
Keputusan desain — Playback (tahap 3) bersifat OPSIONAL dan TIDAK BOLEH
menggagalkan item:

Sejak Phase 4, Playback sengaja dibangun independen: jika PortAudio/driver
audio tidak terdeteksi saat startup, ``playback_manager`` bernilai ``None``
(lihat ``main.py``) tapi server tetap berjalan normal. Prinsip yang sama
dipertahankan di sini — jika ``playback_manager`` adalah ``None``, ATAU
pemutaran gagal karena alasan device/file (mis. device TOA dicabut di
tengah operasional), item TETAP ditandai ``COMPLETED`` oleh ``QueueWorker``
selama sintesis TTS-nya sendiri berhasil. Hanya audio yang tidak terdengar
— ini dicatat sebagai warning di log, bukan exception yang menjalar.

Sebaliknya, kegagalan pada TAHAP TTS (cache/generate) tetap dibiarkan
menjalar sebagai exception tanpa perubahan sama sekali dari kontrak Phase 3
(``TTSQueueProcessor``) — ``QueueWorker`` akan menandai item tsb ``FAILED``.

--------------------------------------------------------------------------
Penambahan Phase 6 — ``volume_gain`` per-Zone:

Setiap Zone (lihat ``zones/manager.py``) punya volume/gain sendiri, analog
volume knob per-channel pada amplifier TOA — independen dari volume
per-item. Menerapkan gain zone LANGSUNG ke file cache akan mencemari cache
(cache di-share oleh SELURUH zone berdasarkan SHA256 dari teks+parameter
TTS, lihat ``tts/cache.py`` — bukan per-zone). Maka gain zone diterapkan
di SINI, tepat sebelum audio diputar, ke SALINAN sementara file audio
(bukan ke file cache aslinya), memakai ulang ``AudioProcessor.apply_volume``
yang sudah ada sejak Phase 3 (tidak diduplikasi). Jika gain total = 1.0,
tahap ini dilewati sepenuhnya dan file diputar langsung.

--------------------------------------------------------------------------
Volume per-item vs gain zone — kenapa penerapannya di titik BERBEDA:

Ada DUA gain yang independen dan keduanya harus ikut terdengar:

- ``item.volume`` — dari request (``SpeakRequest.volume``), per pengumuman.
- ``self._volume_gain`` — gain zone, per zona audio.

Untuk ``type='tts'``, ``item.volume`` sudah lebih dulu dipanggang ke dalam
file cache TTS (``TTSService.synthesize``; ``item.volume`` juga bagian
cache key), sehingga di modul ini TIDAK boleh diterapkan lagi — kalau
begitu, volume ter-kuadrat. Untuk chime dan file statis ``type='audio'``,
``item.volume`` tidak pernah diterapkan di mana pun, jadi justru
diterapkan DI SINI. Rinciannya ada di ``_announcement_gain`` & ``_chime_gain``.

Konsekuensinya, ``volume`` dari request berlaku SERAGAT untuk seluruh file
yang diputar item tersebut (chime, TTS, maupun file statis) — persis
seperti yang diharapkan client, dan tidak ada lagi field yang diam-diam
diabaikan hanya karena jenis audiosinya berbeda.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.core.exceptions import AppError
from announcement_server.playback.manager import PlaybackManager
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import AnnouncementType, QueueItem
from announcement_server.queueing.worker import ItemProcessor
from announcement_server.tts.audio_processor import AudioProcessor

logger = logging.getLogger(__name__)


class AnnouncementPipelineProcessor:
    """Item processor Phase 5: TTS (Phase 3) + Playback (Phase 4) + Delay disatukan."""

    def __init__(
        self,
        tts_processor: ItemProcessor,
        queue_manager: QueueManager,
        playback_manager: PlaybackManager | None,
        *,
        post_playback_delay_seconds: float = 0.5,
        volume_gain: float = 1.0,
        scaled_audio_dir: str | Path | None = None,
        asset_resolver: AudioAssetResolver | None = None,
    ) -> None:
        """Menyimpan komponen pipeline (TTS, queue, playback), delay, gain zone & resolver chime."""
        self._tts_processor = tts_processor
        self._queue_manager = queue_manager
        self._playback_manager = playback_manager
        self._post_playback_delay_seconds = post_playback_delay_seconds
        self._volume_gain = volume_gain
        # Direktori untuk menulis salinan audio yang sudah diberi gain zone
        # (Phase 6). Default ke subfolder di sebelah cache TTS jika tidak
        # diberikan eksplisit. Dibuat lazy (baru saat benar-benar dibutuhkan,
        # yaitu ketika volume_gain != 1.0) supaya zone yang tidak memakai
        # gain custom (mis. "main") tidak membuat direktori kosong.
        self._scaled_audio_dir = Path(scaled_audio_dir) if scaled_audio_dir is not None else Path("cache/zone_audio")
        self._audio_processor = AudioProcessor()
        # Resolver file audio statis (Phase 7, di-share seluruh zone) —
        # dipakai untuk me-resolve & (jika perlu) mengonversi file chime ke
        # WAV sebelum diputar. Opsional: jika None, chime dilewati dengan
        # peringatan di log (mis. saat unit test membangun pipeline tanpa
        # resolver). Lihat `_play_chime` di bawah.
        self._asset_resolver = asset_resolver

    @property
    def volume_gain(self) -> float:
        """Volume/gain zone saat ini (diterapkan sebelum playback; 1.0 = tanpa gain)."""
        return self._volume_gain

    @volume_gain.setter
    def volume_gain(self, value: float) -> None:
        """Mengubah gain zone (dipakai ``PUT /zones/{name}``); berlaku untuk item berikutnya."""
        self._volume_gain = value

    async def __call__(self, item: QueueItem) -> None:
        """Dipanggil oleh QueueWorker untuk setiap item berstatus PROCESSING.

        Exception dari tahap TTS (``self._tts_processor``) SENGAJA dibiarkan
        menjalar ke atas tanpa ditangkap — kontrak ini sudah ada sejak
        Phase 2/3 (``QueueWorker._process_item`` yang akan menandai item
        FAILED). Exception dari tahap Playback DITANGKAP di sini (lihat
        rationale pada docstring modul) supaya tidak mengubah status item
        yang TTS-nya sudah berhasil.
        """
        # Tahap 1-2: Cache -> Generate.
        await self._tts_processor(item)

        # `item` yang dipegang di sini adalah salinan (model_copy) yang
        # diambil QueueWorker SEBELUM tahap TTS di atas berjalan, sehingga
        # `item.audio_file_path`-nya masih None. TTSQueueProcessor meng-update
        # registry lewat `queue_manager.update_tts_result()` (Phase 3), bukan
        # mengubah objek `item` lokal ini. Maka path audio terbaru diambil
        # ulang dari QueueManager, bukan dari `item` di parameter method ini.
        updated_item = await self._queue_manager.get_item(item.id)
        audio_file_path = updated_item.audio_file_path

        if audio_file_path is None:
            logger.warning(
                "Item id=%s tidak memiliki audio_file_path setelah tahap TTS; tahap Playback dilewati.",
                item.id,
            )
        else:
            # Chime (opsional): diputar SEKALI SEBELUM pengumuman utama.
            # Best-effort — jika file chime hilang/tidak bisa di-resolve,
            # pengumuman tetap diputar tanpa chime (lihat `_play_chime`).
            if updated_item.chime_file:
                await self._play_chime(updated_item)
            await self._play_and_wait(item, audio_file_path)

        # Tahap 4: Delay, sebelum QueueWorker melanjutkan ke tahap 5 (Queue Berikutnya).
        if self._post_playback_delay_seconds > 0:
            await asyncio.sleep(self._post_playback_delay_seconds)

    async def _play_chime(self, item: QueueItem) -> None:
        """Memutar efek chime (``item.chime_file``) SEBELUM pengumuman utama.

        Bersifat OPSIONAL & best-effort, konsisten dengan prinsip Playback
        pada modul ini: kegagalan di tahap ini (file tidak ditemukan,
        ffmpeg tidak tersedia, konversi gagal, playback gagal) TIDAK BOLEH
        menggagalkan item — hanya di-log sebagai warning, lalu pengumuman
        utama tetap diputar.
        """
        if self._playback_manager is None:
            return
        if self._asset_resolver is None:
            logger.warning(
                "Chime untuk item id=%s dilewati: pipeline tidak memiliki AudioAssetResolver.",
                item.id,
            )
            return

        try:
            chime_path, _cache_hit = await self._asset_resolver.resolve(item.chime_file)
        except Exception:  # noqa: BLE001 - chime opsional: kegagalan resolve tidak boleh menggagalkan pengumuman
            logger.exception(
                "Chime untuk item id=%s gagal di-resolve (%s); pengumuman tetap diputar tanpa chime.",
                item.id,
                item.chime_file,
            )
            return

        await self._play_audio_file(item, chime_path, label="chime", gain=self._chime_gain(item))

    async def _play_and_wait(self, item: QueueItem, audio_file_path: str) -> None:
        """Tahap 3: Playback. Best-effort — lihat rationale pada docstring modul."""
        if self._playback_manager is None:
            logger.info(
                "Tahap Playback dilewati untuk item id=%s: sistem audio (PortAudio/driver) "
                "tidak tersedia di server ini.",
                item.id,
            )
            return

        await self._play_audio_file(item, audio_file_path, label="pengumuman", gain=self._announcement_gain(item))

    def _announcement_gain(self, item: QueueItem) -> float:
        """Gain total untuk file pengumuman UTAMA, tepat sebelum diputar.

        Dua sumber gain perlu dibedakan karena TITIK penerapannya berbeda:

        - ``type='tts'``: ``item.volume`` dari request sudah dipanggang lebih
          dulu ke dalam file cache TTS (``TTSService.synthesize`` ->
          ``AudioProcessor.apply_volume``; ``item.volume`` juga ikut menjadi
          bagian cache key). Jadi di sini TIDAK boleh diterapkan lagi — kalau
          iya, volumenya jadi ter-kuadrat: request ``volume=1.5`` di-cache
          pada 1.5x, lalu dikalikan 1.5x lagi saat playback -> 2.25x dari yang
          klien minta. Yang perlu diterapkan di sini hanya gain zone.
        - ``type='audio'``: file statis dipakai apa adanya, ``item.volume``
          tidak pernah diterapkan di mana pun. Supaya konsisten dengan
          ``type='tts'`` (dan dengan chime, lihat ``_chime_gain``), volume
          request ikut diterapkan di sini, digabung dengan gain zone.
        """
        if item.announcement_type == AnnouncementType.AUDIO:
            return self._volume_gain * item.volume
        return self._volume_gain

    def _chime_gain(self, item: QueueItem) -> float:
        """Gain total untuk file chime, tepat sebelum diputar.

        Chime TIDAK pernah melewati cache TTS — file-nya datang langsung dari
        ``AudioAssetResolver`` (file WAV sumber, atau hasil konversi ffmpeg
        yang di-cache per-file-sumber). Jadi ``item.volume`` dari request
        belum pernah diterapkan ke file chime, dan harus diterapkan di sini.
        Gain zone ikut dikalikan karena keduanya gain yang independen.
        """
        return self._volume_gain * item.volume

    async def _play_audio_file(self, item: QueueItem, file_path: str, *, label: str, gain: float) -> None:
        """Memutar SATU file audio lalu menunggu tuntas, dengan ``gain`` diterapkan.

        Dipakai bersama oleh pengumuman utama (``_play_and_wait``) dan chime
        (``_play_chime``) — `label` hanya untuk pesan log dan nama file
        sementara ('chime' vs 'pengumuman'). Best-effort: kegagalan playback
        tidak menggagalkan item.
        """
        play_file_path = file_path
        scaled_path: Path | None = None
        if gain != 1.0:
            scaled_path = await asyncio.to_thread(self._write_gain_applied_copy, item.id, label, file_path, gain)
            if scaled_path is not None:
                play_file_path = str(scaled_path)

        try:
            await self._playback_manager.play(play_file_path)
            await self._playback_manager.wait_until_finished()
        except AppError as exc:
            logger.warning(
                "Playback %s gagal untuk item id=%s (%s): %s. Item tetap ditandai selesai "
                "karena sintesis TTS berhasil.",
                label,
                item.id,
                exc.error_code,
                exc.message,
            )
        except Exception:  # noqa: BLE001 - kegagalan playback tidak boleh membatalkan item yang TTS-nya sukses
            logger.exception(
                "Playback %s gagal tak terduga untuk item id=%s. Item tetap ditandai selesai "
                "karena sintesis TTS berhasil.",
                label,
                item.id,
            )
        finally:
            if scaled_path is not None:
                await asyncio.to_thread(self._delete_quietly, scaled_path)

    def _write_gain_applied_copy(self, item_id: uuid.UUID, label: str, audio_file_path: str, gain: float) -> Path | None:
        """Membuat salinan sementara file audio dengan ``gain`` diterapkan.

        File ASLI (di cache TTS untuk pengumuman, atau file sumber/hasil
        konversi di cache announcement untuk chime & file statis) TIDAK
        disentuh sama sekali — hanya dibaca. Mengembalikan ``None`` (playback
        lanjut memakai file asli) jika penerapan gain gagal, supaya kegagalan
        di tahap ini tidak pernah menggagalkan pengumuman yang TTS-nya sudah
        berhasil (prinsip yang sama seperti kegagalan Playback lainnya di
        modul ini).

        ``label`` ikut masuk nama file karena SATU item bisa punya dua file
        yang perlu gain (chime + pengumuman utama) — tanpa itu keduanya akan
        berebut file sementara yang sama.
        """
        try:
            source = Path(audio_file_path)
            original_bytes = source.read_bytes()
            scaled_bytes = self._audio_processor.apply_volume(original_bytes, gain)

            self._scaled_audio_dir.mkdir(parents=True, exist_ok=True)
            scaled_path = self._scaled_audio_dir / f"{item_id}_{label}.wav"
            scaled_path.write_bytes(scaled_bytes)
            return scaled_path
        except Exception:  # noqa: BLE001 - gagal menerapkan gain tidak boleh menggagalkan playback
            logger.exception(
                "Gagal menerapkan gain=%s untuk item id=%s (%s); memutar audio asli tanpa gain.",
                gain,
                item_id,
                label,
            )
            return None

    @staticmethod
    def _delete_quietly(path: Path) -> None:
        """Menghapus file (biasanya salinan audio sementara) tanpa melempar error apa pun."""
        try:
            path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - kegagalan membersihkan file temporer bukan error fatal
            logger.debug("Gagal menghapus file audio sementara: %s", path, exc_info=True)
