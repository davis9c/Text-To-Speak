"""Unit test untuk SchedulerManager (Phase 8).

Memakai ``ZoneManager`` terisolasi (pola sama seperti ``test_zone_manager.py``)
dengan zone 'main' sudah dibuat, supaya ``SchedulerManager`` punya tempat
nyata untuk meng-enqueue tanpa bergantung pada TTS/audio hardware
sungguhan.
"""

from __future__ import annotations

import asyncio
import io
import uuid
import wave
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.core.config import AnnouncementConfig, TTSConfig
from announcement_server.core.exceptions import InvalidScheduleError, ScheduleNotFoundError, ZoneNotFoundError
from announcement_server.queueing.models import AnnouncementType, QueuePriority
from announcement_server.scheduler.manager import SchedulerManager
from announcement_server.scheduler.models import AnnouncementSpec, ScheduleRecurrence
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService
from announcement_server.zones.manager import ZoneManager
from announcement_server.zones.models import MAIN_ZONE_NAME


class FakeEngine(TTSEngine):
    """Engine TTS palsu: menghasilkan WAV valid tanpa memanggil Piper asli."""

    async def synthesize(self, *, text: str, voice: str, speed: float) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(22050)
            writer.writeframes(b"\x00\x00" * 50)
        return buffer.getvalue()


@pytest.fixture(autouse=True)
def register_fake_engine():
    EngineFactory.register("fake_scheduler_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_scheduler_engine"]


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_scheduler_engine", cache_dir=str(tmp_path / "cache"))
    return TTSService(config)


@pytest.fixture()
def asset_resolver(tmp_path: Path) -> AudioAssetResolver:
    config = AnnouncementConfig(
        sounds_dir=str(tmp_path / "sounds"),
        converted_cache_dir=str(tmp_path / "cache_announcement"),
    )
    return AudioAssetResolver(config)


@pytest.fixture()
async def zone_manager(tts_service: TTSService, asset_resolver: AudioAssetResolver):
    manager = ZoneManager(audio_device_manager=None, tts_service=tts_service, asset_resolver=asset_resolver)
    await manager.create_zone(MAIN_ZONE_NAME)
    yield manager
    await manager.shutdown()


@pytest.fixture()
async def scheduler_manager(zone_manager: ZoneManager):
    manager = SchedulerManager(zone_manager, default_voice="default", poll_interval_seconds=0.1)
    yield manager
    await manager.shutdown()


def _tts_spec(text: str = "Halo dunia") -> AnnouncementSpec:
    return AnnouncementSpec(type=AnnouncementType.TTS, text=text, priority=QueuePriority.NORMAL)


# --- CRUD --------------------------------------------------------------


async def test_create_schedule_daily(scheduler_manager: SchedulerManager) -> None:
    entry = await scheduler_manager.create_schedule(
        name="Bell Masuk", recurrence=ScheduleRecurrence.DAILY, time_of_day=time(7, 0), announcement=_tts_spec()
    )
    assert entry.name == "Bell Masuk"
    assert entry.enabled is True
    assert entry.zone == "main"
    assert entry.next_run_at is not None


async def test_create_schedule_weekly_missing_days_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(InvalidScheduleError):
        await scheduler_manager.create_schedule(
            name="Istirahat", recurrence=ScheduleRecurrence.WEEKLY, time_of_day=time(12, 0), announcement=_tts_spec()
        )


async def test_create_schedule_weekly_invalid_day_value_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(InvalidScheduleError):
        await scheduler_manager.create_schedule(
            name="Istirahat",
            recurrence=ScheduleRecurrence.WEEKLY,
            time_of_day=time(12, 0),
            days_of_week=[7],
            announcement=_tts_spec(),
        )


async def test_create_schedule_once_missing_run_date_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(InvalidScheduleError):
        await scheduler_manager.create_schedule(
            name="Pengumuman Khusus", recurrence=ScheduleRecurrence.ONCE, time_of_day=time(9, 0), announcement=_tts_spec()
        )


async def test_create_schedule_once_past_date_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(InvalidScheduleError):
        await scheduler_manager.create_schedule(
            name="Sudah Lewat",
            recurrence=ScheduleRecurrence.ONCE,
            time_of_day=time(9, 0),
            run_date=date(2020, 1, 1),
            announcement=_tts_spec(),
        )


async def test_create_schedule_invalid_announcement_tts_without_text_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(InvalidScheduleError):
        await scheduler_manager.create_schedule(
            name="Kosong",
            recurrence=ScheduleRecurrence.DAILY,
            time_of_day=time(7, 0),
            announcement=AnnouncementSpec(type=AnnouncementType.TTS, text=None),
        )


async def test_create_schedule_invalid_announcement_audio_without_file_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(InvalidScheduleError):
        await scheduler_manager.create_schedule(
            name="Kosong",
            recurrence=ScheduleRecurrence.DAILY,
            time_of_day=time(7, 0),
            announcement=AnnouncementSpec(type=AnnouncementType.AUDIO, file=None),
        )


async def test_get_schedule_not_found(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(ScheduleNotFoundError):
        scheduler_manager.get_schedule(uuid.uuid4())


async def test_list_schedules(scheduler_manager: SchedulerManager) -> None:
    await scheduler_manager.create_schedule(
        name="A", recurrence=ScheduleRecurrence.DAILY, time_of_day=time(7, 0), announcement=_tts_spec()
    )
    await scheduler_manager.create_schedule(
        name="B", recurrence=ScheduleRecurrence.DAILY, time_of_day=time(8, 0), announcement=_tts_spec()
    )
    assert {entry.name for entry in scheduler_manager.list_schedules()} == {"A", "B"}


async def test_update_schedule_partial(scheduler_manager: SchedulerManager) -> None:
    entry = await scheduler_manager.create_schedule(
        name="Bell", recurrence=ScheduleRecurrence.DAILY, time_of_day=time(7, 0), announcement=_tts_spec()
    )
    updated = await scheduler_manager.update_schedule(entry.id, enabled=False)
    assert updated.enabled is False
    assert updated.name == "Bell"  # tidak berubah karena tidak dikirim


async def test_update_schedule_recurrence_recomputes_next_run(scheduler_manager: SchedulerManager) -> None:
    entry = await scheduler_manager.create_schedule(
        name="Bell", recurrence=ScheduleRecurrence.DAILY, time_of_day=time(7, 0), announcement=_tts_spec()
    )
    updated = await scheduler_manager.update_schedule(
        entry.id, recurrence=ScheduleRecurrence.WEEKLY, days_of_week=[0, 1, 2, 3, 4]
    )
    assert updated.recurrence == ScheduleRecurrence.WEEKLY
    assert updated.next_run_at is not None


async def test_update_schedule_weekly_removing_days_raises(scheduler_manager: SchedulerManager) -> None:
    entry = await scheduler_manager.create_schedule(
        name="Istirahat",
        recurrence=ScheduleRecurrence.WEEKLY,
        time_of_day=time(12, 0),
        days_of_week=[0, 1],
        announcement=_tts_spec(),
    )
    with pytest.raises(InvalidScheduleError):
        await scheduler_manager.update_schedule(entry.id, days_of_week=[])


async def test_update_schedule_not_found_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(ScheduleNotFoundError):
        await scheduler_manager.update_schedule(uuid.uuid4(), enabled=False)


async def test_delete_schedule(scheduler_manager: SchedulerManager) -> None:
    entry = await scheduler_manager.create_schedule(
        name="Bell", recurrence=ScheduleRecurrence.DAILY, time_of_day=time(7, 0), announcement=_tts_spec()
    )
    await scheduler_manager.delete_schedule(entry.id)
    with pytest.raises(ScheduleNotFoundError):
        scheduler_manager.get_schedule(entry.id)


async def test_delete_schedule_not_found_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(ScheduleNotFoundError):
        await scheduler_manager.delete_schedule(uuid.uuid4())


# --- Trigger manual ----------------------------------------------------


async def test_trigger_now_enqueues_item_without_changing_next_run(
    scheduler_manager: SchedulerManager, zone_manager: ZoneManager
) -> None:
    entry = await scheduler_manager.create_schedule(
        name="Bell", recurrence=ScheduleRecurrence.DAILY, time_of_day=time(7, 0), announcement=_tts_spec("Uji coba")
    )
    original_next_run = entry.next_run_at

    item = await scheduler_manager.trigger_now(entry.id)
    assert item.text == "Uji coba"

    after_trigger = scheduler_manager.get_schedule(entry.id)
    assert after_trigger.next_run_at == original_next_run
    assert after_trigger.last_triggered_at is None  # trigger_now TIDAK menandai last_triggered_at (bukan siklus otomatis)

    queue_manager = zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    items = await queue_manager.list_items()
    assert len(items) == 1


async def test_trigger_now_unknown_zone_raises(scheduler_manager: SchedulerManager) -> None:
    entry = await scheduler_manager.create_schedule(
        name="Zone Hilang",
        recurrence=ScheduleRecurrence.DAILY,
        time_of_day=time(7, 0),
        zone="zone-tidak-ada",
        announcement=_tts_spec(),
    )
    with pytest.raises(ZoneNotFoundError):
        await scheduler_manager.trigger_now(entry.id)


async def test_trigger_now_schedule_not_found_raises(scheduler_manager: SchedulerManager) -> None:
    with pytest.raises(ScheduleNotFoundError):
        await scheduler_manager.trigger_now(uuid.uuid4())


# --- Background loop (real, poll_interval_seconds pendek) ----------------------


async def _wait_until(condition, timeout: float = 3.0, interval: float = 0.02) -> None:
    elapsed = 0.0
    while not condition():
        if elapsed >= timeout:
            raise AssertionError("Timeout menunggu kondisi terpenuhi.")
        await asyncio.sleep(interval)
        elapsed += interval


async def test_background_loop_fires_once_schedule_automatically(
    scheduler_manager: SchedulerManager, zone_manager: ZoneManager
) -> None:
    """Jadwal ONCE yang jatuh tempo sangat dekat HARUS benar-benar terpicu otomatis oleh
    background loop (bukan hanya lewat trigger_now manual) dalam beberapa poll cycle."""
    near_future = datetime.now() + timedelta(seconds=0.3)

    entry = await scheduler_manager.create_schedule(
        name="Segera",
        recurrence=ScheduleRecurrence.ONCE,
        time_of_day=near_future.time(),
        run_date=near_future.date(),
        announcement=_tts_spec("Terpicu otomatis"),
    )

    scheduler_manager.start()
    try:
        await _wait_until(lambda: scheduler_manager.get_schedule(entry.id).last_triggered_at is not None)
    finally:
        await scheduler_manager.stop()

    fired_entry = scheduler_manager.get_schedule(entry.id)
    assert fired_entry.enabled is False  # ONCE otomatis dinonaktifkan setelah terpicu
    assert fired_entry.next_run_at is None

    queue_manager = zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    items = await queue_manager.list_items()
    assert any(item.text == "Terpicu otomatis" for item in items)


async def test_scheduler_start_is_idempotent(scheduler_manager: SchedulerManager) -> None:
    scheduler_manager.start()
    scheduler_manager.start()  # tidak boleh melempar / membuat task kedua
    assert scheduler_manager.is_running is True
    await scheduler_manager.stop()
    assert scheduler_manager.is_running is False


async def test_scheduler_stop_without_start_is_safe(scheduler_manager: SchedulerManager) -> None:
    await scheduler_manager.stop()  # tidak boleh melempar walau belum pernah start()
    assert scheduler_manager.is_running is False
