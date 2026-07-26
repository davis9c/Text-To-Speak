"""Test HTTP untuk Phase 10 (Dashboard API) — `/status`, `/history`, `/metrics`.

Seluruh komponen (``ZoneManager``, ``SchedulerManager``, ``TTSService``,
``AudioAssetResolver``, ``ConnectionManager``) di-override lewat
``app.dependency_overrides`` menjadi instance terisolasi (pola sama
seperti ``test_scheduler_api.py``/``test_zones_api.py``) — supaya tidak
terpengaruh oleh state aplikasi sungguhan (3 contoh jadwal, cache TTS
nyata, dst) dan tidak butuh Piper/hardware audio sungguhan.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Iterator
from datetime import time as dt_time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.api.deps import (
    get_asset_resolver,
    get_connection_manager,
    get_scheduler_manager,
    get_tts_service,
    get_zone_manager,
)
from announcement_server.core.config import AnnouncementConfig, TTSConfig, get_settings
from announcement_server.main import create_app
from announcement_server.queueing.models import AnnouncementType, QueuePriority
from announcement_server.scheduler.manager import SchedulerManager
from announcement_server.scheduler.models import AnnouncementSpec, ScheduleRecurrence
from announcement_server.tts.engine_base import TTSEngine
from announcement_server.tts.engine_factory import EngineFactory
from announcement_server.tts.service import TTSService
from announcement_server.websocket.manager import ConnectionManager
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
    EngineFactory.register("fake_dashboard_engine", FakeEngine)
    yield
    del EngineFactory._registry["fake_dashboard_engine"]


@pytest.fixture()
def tts_service(tmp_path: Path) -> TTSService:
    config = TTSConfig(engine="fake_dashboard_engine", cache_dir=str(tmp_path / "cache_tts"))
    return TTSService(config)


@pytest.fixture()
def asset_resolver(tmp_path: Path) -> AudioAssetResolver:
    config = AnnouncementConfig(
        sounds_dir=str(tmp_path / "sounds"),
        converted_cache_dir=str(tmp_path / "cache_announcement"),
    )
    return AudioAssetResolver(config)


@pytest.fixture()
def connection_manager() -> ConnectionManager:
    return ConnectionManager()


@pytest.fixture()
async def zone_manager(
    tts_service: TTSService, asset_resolver: AudioAssetResolver, connection_manager: ConnectionManager
) -> Iterator[ZoneManager]:
    manager = ZoneManager(
        audio_device_manager=None,
        tts_service=tts_service,
        asset_resolver=asset_resolver,
        event_publisher=connection_manager.broadcast,
    )
    await manager.create_zone(MAIN_ZONE_NAME)
    yield manager
    await manager.shutdown()


@pytest.fixture()
async def scheduler_manager(zone_manager: ZoneManager) -> Iterator[SchedulerManager]:
    manager = SchedulerManager(zone_manager, default_voice="default", poll_interval_seconds=60.0)
    yield manager
    await manager.shutdown()


@pytest.fixture()
def client(
    zone_manager: ZoneManager,
    scheduler_manager: SchedulerManager,
    tts_service: TTSService,
    asset_resolver: AudioAssetResolver,
    connection_manager: ConnectionManager,
) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_zone_manager] = lambda: zone_manager
    app.dependency_overrides[get_scheduler_manager] = lambda: scheduler_manager
    app.dependency_overrides[get_tts_service] = lambda: tts_service
    app.dependency_overrides[get_asset_resolver] = lambda: asset_resolver
    app.dependency_overrides[get_connection_manager] = lambda: connection_manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


# --- GET /status ---------------------------------------------------------


def test_status_returns_all_sections(client: TestClient) -> None:
    response = client.get("/status")
    assert response.status_code == 200
    body = response.json()

    assert body["app_name"]
    assert body["version"]
    assert body["uptime_seconds"] >= 0
    assert {zone["name"] for zone in body["zones"]} == {MAIN_ZONE_NAME}
    assert body["tts_cache"]["file_count"] == 0
    assert body["announcement_cache"]["file_count"] == 0
    assert body["connected_websocket_clients"] == 0


def test_status_reflects_new_zone(client: TestClient) -> None:
    client.post("/zones", json={"name": "lobby"})
    body = client.get("/status").json()
    assert {zone["name"] for zone in body["zones"]} == {MAIN_ZONE_NAME, "lobby"}


def test_status_zone_shows_pending_count(client: TestClient) -> None:
    client.post(f"/zones/{MAIN_ZONE_NAME}/speak", json={"text": "Halo dunia"})
    body = client.get("/status").json()
    main_zone = next(z for z in body["zones"] if z["name"] == MAIN_ZONE_NAME)
    assert main_zone["pending_count"] == 1


# --- GET /history ---------------------------------------------------------


async def test_history_returns_finished_items_only(client: TestClient, zone_manager: ZoneManager) -> None:
    queue_manager = zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    pending_item = await queue_manager.enqueue("Masih pending", QueuePriority.NORMAL)
    completed_item = await queue_manager.enqueue("Sudah selesai", QueuePriority.NORMAL)
    await queue_manager.dequeue_for_processing()  # ambil pending_item lebih dulu (FIFO)
    await queue_manager.mark_failed(pending_item.id, "sengaja gagal")
    await queue_manager.dequeue_for_processing()
    await queue_manager.mark_completed(completed_item.id)

    response = client.get("/history")
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {str(pending_item.id), str(completed_item.id)}
    for item in body["items"]:
        assert item["zone"] == MAIN_ZONE_NAME


def test_history_empty_initially(client: TestClient) -> None:
    response = client.get("/history")
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


async def test_history_status_filter(client: TestClient, zone_manager: ZoneManager) -> None:
    queue_manager = zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    item = await queue_manager.enqueue("Gagal", QueuePriority.NORMAL)
    await queue_manager.dequeue_for_processing()
    await queue_manager.mark_failed(item.id, "error")

    response = client.get("/history", params={"status": "failed"})
    assert response.json()["count"] == 1

    response_completed = client.get("/history", params={"status": "completed"})
    assert response_completed.json()["count"] == 0


async def test_history_zone_filter(client: TestClient, zone_manager: ZoneManager) -> None:
    await zone_manager.create_zone("lobby")
    main_queue = zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    lobby_queue = zone_manager.get_queue_manager("lobby")

    main_item = await main_queue.enqueue("Main", QueuePriority.NORMAL)
    await main_queue.dequeue_for_processing()
    await main_queue.mark_completed(main_item.id)

    lobby_item = await lobby_queue.enqueue("Lobby", QueuePriority.NORMAL)
    await lobby_queue.dequeue_for_processing()
    await lobby_queue.mark_completed(lobby_item.id)

    response = client.get("/history", params={"zone": "lobby"})
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["zone"] == "lobby"


def test_history_unknown_zone_returns_404(client: TestClient) -> None:
    response = client.get("/history", params={"zone": "tidak-ada"})
    assert response.status_code == 404


async def test_history_limit(client: TestClient, zone_manager: ZoneManager) -> None:
    queue_manager = zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    for i in range(5):
        item = await queue_manager.enqueue(f"Item {i}", QueuePriority.NORMAL)
        await queue_manager.dequeue_for_processing()
        await queue_manager.mark_completed(item.id)

    response = client.get("/history", params={"limit": 2})
    assert response.json()["count"] == 2


async def test_history_sorted_most_recent_first(client: TestClient, zone_manager: ZoneManager) -> None:
    queue_manager = zone_manager.get_queue_manager(MAIN_ZONE_NAME)
    first = await queue_manager.enqueue("Pertama", QueuePriority.NORMAL)
    await queue_manager.dequeue_for_processing()
    await queue_manager.mark_completed(first.id)

    second = await queue_manager.enqueue("Kedua", QueuePriority.NORMAL)
    await queue_manager.dequeue_for_processing()
    await queue_manager.mark_completed(second.id)

    body = client.get("/history").json()
    assert body["items"][0]["id"] == str(second.id)
    assert body["items"][1]["id"] == str(first.id)


# --- GET /metrics ---------------------------------------------------------


def test_metrics_returns_zero_counts_initially(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["zones_count"] == 1
    assert body["total_items_by_status"] == {}
    assert body["active_schedules_count"] == 0
    assert body["connected_websocket_clients"] == 0


def test_metrics_counts_items_by_status(client: TestClient) -> None:
    client.post(f"/zones/{MAIN_ZONE_NAME}/speak", json={"text": "Halo"})
    body = client.get("/metrics").json()
    assert body["total_items_by_status"] == {"pending": 1}


async def test_metrics_counts_active_schedules(client: TestClient, scheduler_manager: SchedulerManager) -> None:
    await scheduler_manager.create_schedule(
        name="Bell",
        recurrence=ScheduleRecurrence.DAILY,
        time_of_day=dt_time(7, 0),
        announcement=AnnouncementSpec(type=AnnouncementType.TTS, text="Bel masuk", priority=QueuePriority.NORMAL),
    )
    await scheduler_manager.create_schedule(
        name="Nonaktif",
        enabled=False,
        recurrence=ScheduleRecurrence.DAILY,
        time_of_day=dt_time(8, 0),
        announcement=AnnouncementSpec(type=AnnouncementType.TTS, text="Tidak aktif", priority=QueuePriority.NORMAL),
    )

    body = client.get("/metrics").json()
    assert body["active_schedules_count"] == 1
