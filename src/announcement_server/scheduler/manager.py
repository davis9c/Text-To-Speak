"""Scheduler Manager (Phase 8).

Mengelola siklus hidup jadwal (CRUD, pola yang sama dengan ``ZoneManager``,
Phase 6) dan menjalankan SATU background task (pola yang sama dengan
``QueueWorker``, Phase 2 — lihat ``queueing/worker.py``) yang secara
berkala memeriksa jadwal mana yang sudah jatuh tempo, lalu meng-enqueue
pengumumannya lewat ``QueueManager.enqueue()`` milik zone tujuan (Phase
2/6/7, TIDAK diubah/diduplikasi sama sekali).

SchedulerManager TIDAK memproses TTS/audio/playback apa pun sendiri — itu
sepenuhnya tetap tanggung jawab pipeline yang sudah ada (Phase 3-7).
Tanggung jawabnya murni SATU hal: pada waktu yang tepat, memasukkan item
ke antrean yang sudah ada.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, time, tzinfo

from announcement_server.core.exceptions import InvalidScheduleError, ScheduleNotFoundError, ZoneNotFoundError
from announcement_server.queueing.manager import QueueManager
from announcement_server.queueing.models import AnnouncementType, QueueItem
from announcement_server.scheduler.models import AnnouncementSpec, ScheduleEntry, ScheduleRecurrence, compute_next_run
from announcement_server.zones.manager import ZoneManager

logger = logging.getLogger(__name__)

# Sentinel untuk membedakan "field tidak diberikan sama sekali" (pertahankan
# nilai lama) dari "field diberikan bernilai None/0" pada `update_schedule` —
# pola yang sama seperti `_UNSET` pada `zones/manager.py`.
_UNSET = object()


def _validate_announcement(spec: AnnouncementSpec) -> None:
    """Konsistensi `type` vs `text`/`file` — logika identik dengan validator ``SpeakRequest`` (Phase 2/7)."""
    if spec.type == AnnouncementType.TTS:
        if not spec.text or not spec.text.strip():
            raise InvalidScheduleError("`announcement.text` wajib diisi (tidak boleh kosong) untuk type='tts'.")
    else:
        if not spec.file or not spec.file.strip():
            raise InvalidScheduleError("`announcement.file` wajib diisi (tidak boleh kosong) untuk type='audio'.")


def _validate_recurrence(recurrence: ScheduleRecurrence, days_of_week: list[int] | None, run_date: date | None) -> None:
    if recurrence == ScheduleRecurrence.WEEKLY:
        if not days_of_week:
            raise InvalidScheduleError("`days_of_week` wajib diisi (minimal 1 hari) untuk recurrence='weekly'.")
        if any(day < 0 or day > 6 for day in days_of_week):
            raise InvalidScheduleError("`days_of_week` harus berisi angka 0 (Senin) sampai 6 (Minggu).")
    elif recurrence == ScheduleRecurrence.ONCE:
        if run_date is None:
            raise InvalidScheduleError("`run_date` wajib diisi untuk recurrence='once'.")


class SchedulerManager:
    """Registry jadwal + background loop pemicu pengumuman berbasis waktu."""

    def __init__(
        self,
        zone_manager: ZoneManager,
        *,
        default_voice: str = "default",
        poll_interval_seconds: float = 5.0,
        tz: tzinfo | None = None,
    ) -> None:
        self._zone_manager = zone_manager
        self._default_voice = default_voice
        self._poll_interval_seconds = poll_interval_seconds
        self._tz = tz  # None = "local" (naive datetime, ikut jam sistem)
        self._schedules: dict[uuid.UUID, ScheduleEntry] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    # --- CRUD --------------------------------------------------------------

    async def create_schedule(
        self,
        *,
        name: str,
        announcement: AnnouncementSpec,
        recurrence: ScheduleRecurrence,
        time_of_day: time,
        enabled: bool = True,
        zone: str = "main",
        days_of_week: list[int] | None = None,
        run_date: date | None = None,
    ) -> ScheduleEntry:
        """Mendaftarkan jadwal baru. Melempar ``InvalidScheduleError`` jika konfigurasi tidak valid
        atau hasilnya tidak akan pernah terpicu (mis. `once` dengan tanggal yang sudah lewat)."""
        _validate_announcement(announcement)
        _validate_recurrence(recurrence, days_of_week, run_date)

        now = self._now()
        next_run = compute_next_run(
            recurrence=recurrence, time_of_day=time_of_day, days_of_week=days_of_week, run_date=run_date, after=now
        )
        if next_run is None:
            raise InvalidScheduleError(
                "Konfigurasi jadwal tidak akan pernah terpicu (mis. tanggal 'once' sudah lewat).",
                details={"recurrence": recurrence.value},
            )

        entry = ScheduleEntry(
            id=uuid.uuid4(),
            name=name,
            enabled=enabled,
            zone=zone,
            recurrence=recurrence,
            time_of_day=time_of_day,
            days_of_week=days_of_week,
            run_date=run_date,
            announcement=announcement,
            last_triggered_at=None,
            next_run_at=next_run,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._schedules[entry.id] = entry
        logger.info(
            "Jadwal dibuat: id=%s name=%r recurrence=%s zone=%s next_run_at=%s",
            entry.id,
            entry.name,
            recurrence.value,
            zone,
            next_run.isoformat(),
        )
        return entry.model_copy(deep=True)

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        name: str = _UNSET,  # type: ignore[assignment]
        enabled: bool = _UNSET,  # type: ignore[assignment]
        zone: str = _UNSET,  # type: ignore[assignment]
        recurrence: ScheduleRecurrence = _UNSET,  # type: ignore[assignment]
        time_of_day: time = _UNSET,  # type: ignore[assignment]
        days_of_week: list[int] | None = _UNSET,  # type: ignore[assignment]
        run_date: date | None = _UNSET,  # type: ignore[assignment]
        announcement: AnnouncementSpec = _UNSET,  # type: ignore[assignment]
    ) -> ScheduleEntry:
        """Memperbarui sebagian atau seluruh atribut jadwal (pembaruan parsial, field tak diberikan tak diubah)."""
        entry = self._schedules.get(schedule_id)
        if entry is None:
            raise ScheduleNotFoundError(f"Jadwal '{schedule_id}' tidak ditemukan.", details={"schedule_id": str(schedule_id)})

        if name is not _UNSET:
            entry.name = name
        if enabled is not _UNSET:
            entry.enabled = enabled
        if zone is not _UNSET:
            entry.zone = zone
        if recurrence is not _UNSET:
            entry.recurrence = recurrence
        if time_of_day is not _UNSET:
            entry.time_of_day = time_of_day
        if days_of_week is not _UNSET:
            entry.days_of_week = days_of_week
        if run_date is not _UNSET:
            entry.run_date = run_date
        if announcement is not _UNSET:
            _validate_announcement(announcement)
            entry.announcement = announcement

        _validate_recurrence(entry.recurrence, entry.days_of_week, entry.run_date)

        now = self._now()
        next_run = compute_next_run(
            recurrence=entry.recurrence,
            time_of_day=entry.time_of_day,
            days_of_week=entry.days_of_week,
            run_date=entry.run_date,
            after=now,
        )
        # `next_run=None` valid & diterima untuk ONCE (sudah pernah terpicu, atau
        # run_date memang di masa lalu) — hanya dianggap error untuk WEEKLY yang
        # kehilangan `days_of_week` valid. DAILY tidak pernah menghasilkan None.
        if next_run is None and entry.recurrence == ScheduleRecurrence.WEEKLY:
            raise InvalidScheduleError(
                "Konfigurasi jadwal 'weekly' tidak valid setelah pembaruan.",
                details={"days_of_week": entry.days_of_week},
            )
        entry.next_run_at = next_run
        entry.updated_at = now

        logger.info("Jadwal diperbarui: id=%s name=%r enabled=%s next_run_at=%s", entry.id, entry.name, entry.enabled, next_run)
        return entry.model_copy(deep=True)

    async def delete_schedule(self, schedule_id: uuid.UUID) -> None:
        async with self._lock:
            entry = self._schedules.pop(schedule_id, None)
        if entry is None:
            raise ScheduleNotFoundError(f"Jadwal '{schedule_id}' tidak ditemukan.", details={"schedule_id": str(schedule_id)})
        logger.info("Jadwal dihapus: id=%s name=%r", entry.id, entry.name)

    # --- Lookup --------------------------------------------------------------

    def get_schedule(self, schedule_id: uuid.UUID) -> ScheduleEntry:
        entry = self._schedules.get(schedule_id)
        if entry is None:
            raise ScheduleNotFoundError(f"Jadwal '{schedule_id}' tidak ditemukan.", details={"schedule_id": str(schedule_id)})
        return entry.model_copy(deep=True)

    def list_schedules(self) -> list[ScheduleEntry]:
        return [entry.model_copy(deep=True) for entry in self._schedules.values()]

    # --- Trigger manual (mis. untuk testing/verifikasi) -------------------------

    async def trigger_now(self, schedule_id: uuid.UUID) -> QueueItem:
        """Memicu satu jadwal SEGERA, TANPA memengaruhi `next_run_at` terjadwal (murni untuk verifikasi manual)."""
        entry = self._schedules.get(schedule_id)
        if entry is None:
            raise ScheduleNotFoundError(f"Jadwal '{schedule_id}' tidak ditemukan.", details={"schedule_id": str(schedule_id)})
        return await self._enqueue_announcement(entry)

    # --- Lifecycle (pola identik QueueWorker, Phase 2) --------------------------

    def start(self) -> None:
        """Memulai scheduler sebagai asyncio background task. Idempotent."""
        if self._task is not None:
            logger.warning("SchedulerManager sudah berjalan, pemanggilan start() diabaikan.")
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="scheduler-manager")
        logger.info("SchedulerManager dimulai (poll_interval_seconds=%s).", self._poll_interval_seconds)

    async def stop(self) -> None:
        """Menghentikan scheduler secara graceful. Dipanggil saat aplikasi shutdown."""
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("SchedulerManager dihentikan.")

    async def _run(self) -> None:
        while self._running:
            try:
                await self._check_due_schedules()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - jaring pengaman: loop scheduler TIDAK BOLEH mati
                logger.exception("Unexpected error pada SchedulerManager loop; melanjutkan setelah jeda singkat.")
            await asyncio.sleep(self._poll_interval_seconds)

    async def _check_due_schedules(self) -> None:
        now = self._now()
        async with self._lock:
            due_ids = [
                entry.id
                for entry in self._schedules.values()
                if entry.enabled and entry.next_run_at is not None and entry.next_run_at <= now
            ]
        for schedule_id in due_ids:
            await self._fire(schedule_id, now)

    async def _fire(self, schedule_id: uuid.UUID, now: datetime) -> None:
        entry = self._schedules.get(schedule_id)
        if entry is None:
            return  # sudah dihapus di antara pengecekan due & pemicuan

        try:
            await self._enqueue_announcement(entry)
        except Exception:  # noqa: BLE001 - kegagalan satu jadwal (mis. zone tujuan hilang) tidak boleh mematikan loop
            logger.exception("Gagal meng-enqueue pengumuman untuk jadwal id=%s name=%r", entry.id, entry.name)

        # Majukan next_run_at (atau nonaktifkan jika ONCE) TERLEPAS dari sukses/
        # gagalnya enqueue di atas — kegagalan sudah di-log; membiarkan next_run_at
        # tetap di masa lalu akan membuatnya terpicu ulang setiap poll cycle (retry rapat).
        async with self._lock:
            current = self._schedules.get(entry.id)
            if current is None:
                return
            if current.recurrence == ScheduleRecurrence.ONCE:
                current.next_run_at = None
                current.enabled = False
            else:
                current.next_run_at = compute_next_run(
                    recurrence=current.recurrence,
                    time_of_day=current.time_of_day,
                    days_of_week=current.days_of_week,
                    run_date=current.run_date,
                    after=now,
                )
            current.last_triggered_at = now
            current.updated_at = now

    async def _enqueue_announcement(self, entry: ScheduleEntry) -> QueueItem:
        try:
            queue_manager: QueueManager = self._zone_manager.get_queue_manager(entry.zone)
        except ZoneNotFoundError:
            logger.warning(
                "Jadwal id=%s name=%r menunjuk ke zone '%s' yang tidak ditemukan — dilewati.",
                entry.id,
                entry.name,
                entry.zone,
            )
            raise

        spec = entry.announcement
        text = spec.text if spec.type == AnnouncementType.TTS else (spec.text or f"[audio] {spec.file}")
        item = await queue_manager.enqueue(
            text=text,
            priority=spec.priority,
            voice=spec.voice or self._default_voice,
            speed=spec.speed,
            pitch=spec.pitch,
            volume=spec.volume,
            announcement_type=spec.type,
            source_file=spec.file,
        )
        logger.info("Jadwal terpicu: id=%s name=%r -> item id=%s (zone=%s)", entry.id, entry.name, item.id, entry.zone)
        return item

    # --- Lifecycle helper untuk main.py (bootstrap dari config.yaml) ------------

    async def shutdown(self) -> None:
        """Alias ``stop()`` — dipanggil dari ``main.py`` lifespan agar konsisten dengan ``ZoneManager.shutdown()``."""
        await self.stop()
