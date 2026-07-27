"""Test HTTP untuk Phase 14 — POST /maintenance/cache/cleanup."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.announcement.asset_resolver import AudioAssetResolver
from announcement_server.api.deps import get_asset_resolver, get_tts_service
from announcement_server.core.config import AnnouncementConfig, TTSConfig, get_settings
from announcement_server.main import create_app
from announcement_server.tts.service import TTSService


def _touch_with_age(path: Path, age_days: float) -> None:
    path.write_bytes(b"x" * 10)
    old_time = time.time() - (age_days * 86400)
    os.utime(path, (old_time, old_time))


@pytest.fixture()
def tts_cache_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "cache_tts"
    directory.mkdir()
    return directory


@pytest.fixture()
def announcement_cache_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "cache_announcement"
    directory.mkdir()
    return directory


@pytest.fixture()
def tts_service(tts_cache_dir: Path) -> TTSService:
    return TTSService(TTSConfig(cache_dir=str(tts_cache_dir)))


@pytest.fixture()
def asset_resolver(tmp_path: Path, announcement_cache_dir: Path) -> AudioAssetResolver:
    config = AnnouncementConfig(sounds_dir=str(tmp_path / "sounds"), converted_cache_dir=str(announcement_cache_dir))
    return AudioAssetResolver(config)


@pytest.fixture()
def client(tts_service: TTSService, asset_resolver: AudioAssetResolver) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_tts_service] = lambda: tts_service
    app.dependency_overrides[get_asset_resolver] = lambda: asset_resolver
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_cleanup_with_no_max_age_deletes_nothing(client: TestClient, tts_cache_dir: Path) -> None:
    _touch_with_age(tts_cache_dir / "old.wav", age_days=100)
    response = client.post("/maintenance/cache/cleanup", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["tts_cache"] == {"deleted_count": 0, "freed_bytes": 0}
    assert (tts_cache_dir / "old.wav").exists()


def test_cleanup_deletes_old_tts_cache_files(client: TestClient, tts_cache_dir: Path) -> None:
    _touch_with_age(tts_cache_dir / "old.wav", age_days=10)
    _touch_with_age(tts_cache_dir / "new.wav", age_days=1)

    response = client.post("/maintenance/cache/cleanup", json={"tts_max_age_days": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["tts_cache"]["deleted_count"] == 1
    assert not (tts_cache_dir / "old.wav").exists()
    assert (tts_cache_dir / "new.wav").exists()


def test_cleanup_deletes_old_announcement_cache_files(client: TestClient, announcement_cache_dir: Path) -> None:
    _touch_with_age(announcement_cache_dir / "old.wav", age_days=10)

    response = client.post("/maintenance/cache/cleanup", json={"announcement_max_age_days": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["announcement_cache"]["deleted_count"] == 1
    assert not (announcement_cache_dir / "old.wav").exists()


def test_cleanup_both_caches_independently(client: TestClient, tts_cache_dir: Path, announcement_cache_dir: Path) -> None:
    _touch_with_age(tts_cache_dir / "old.wav", age_days=10)
    _touch_with_age(announcement_cache_dir / "old.wav", age_days=10)

    response = client.post(
        "/maintenance/cache/cleanup", json={"tts_max_age_days": 5, "announcement_max_age_days": 5}
    )

    body = response.json()
    assert body["tts_cache"]["deleted_count"] == 1
    assert body["announcement_cache"]["deleted_count"] == 1


def test_cleanup_negative_max_age_returns_422(client: TestClient) -> None:
    response = client.post("/maintenance/cache/cleanup", json={"tts_max_age_days": -1})
    assert response.status_code == 422


def test_cleanup_empty_body_uses_defaults(client: TestClient) -> None:
    response = client.post("/maintenance/cache/cleanup", json={})
    assert response.status_code == 200
