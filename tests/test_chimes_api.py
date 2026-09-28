"""Test HTTP untuk Chime Discovery API — GET /chimes.

Fitur: file audio chime disimpan di folder khusus ``announcement.chime_dir``
(default ``sounds/chime``) dan didaftarkan lewat ``GET /chimes`` supaya
client bisa menampilkan dropdown pemilihan chime.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.announcement.chime_catalog import ChimeCatalog
from announcement_server.api.deps import get_chime_catalog
from announcement_server.core.config import AnnouncementConfig, get_settings
from announcement_server.main import create_app


@pytest.fixture()
def sounds_dir(tmp_path: Path) -> Path:
    return tmp_path / "sounds"


@pytest.fixture()
def chime_dir(sounds_dir: Path) -> Path:
    return sounds_dir / "chime"


@pytest.fixture()
def chime_catalog(sounds_dir: Path, chime_dir: Path) -> ChimeCatalog:
    return ChimeCatalog(AnnouncementConfig(sounds_dir=str(sounds_dir), chime_dir=str(chime_dir)))


@pytest.fixture()
def client(chime_catalog: ChimeCatalog) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_chime_catalog] = lambda: chime_catalog
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


# --- GET /chimes -------------------------------------------------------------


def test_list_chimes_empty_when_directory_missing(client: TestClient) -> None:
    """Direktori chime belum dibuat → daftar kosong (bukan error)."""
    response = client.get("/chimes")
    assert response.status_code == 200
    body = response.json()
    assert body["chimes"] == []
    assert body["count"] == 0
    assert body["default_chime"] is None


def test_list_chimes_empty_when_directory_has_no_audio_files(client: TestClient, chime_dir: Path) -> None:
    """Hanya file non-audio (mis. README) → tetap diabaikan."""
    chime_dir.mkdir(parents=True)
    (chime_dir / "README.txt").write_text("bukan audio", encoding="utf-8")
    response = client.get("/chimes")
    assert response.status_code == 200
    assert response.json()["chimes"] == []


def test_list_chimes_returns_audio_files_with_relative_paths(client: TestClient, chime_dir: Path) -> None:
    """File WAV di direktori chime muncul dengan `file` relatif terhadap sounds_dir."""
    chime_dir.mkdir(parents=True)
    (chime_dir / "chime.wav").write_bytes(b"RIFF")
    (chime_dir / "bell.wav").write_bytes(b"RIFF")
    (chime_dir / "alarm.mp3").write_bytes(b"ID3")

    response = client.get("/chimes")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3

    by_id = {chime["id"]: chime for chime in body["chimes"]}
    assert set(by_id) == {"chime", "bell", "alarm"}
    assert by_id["chime"]["name"] == "chime"
    assert by_id["chime"]["file"] == "chime/chime.wav"
    assert by_id["chime"]["is_default"] is True
    assert by_id["bell"]["file"] == "chime/bell.wav"
    assert by_id["bell"]["is_default"] is False
    assert by_id["alarm"]["file"] == "chime/alarm.mp3"
    assert body["default_chime"] == "chime/chime.wav"


def test_list_chimes_sorted_and_marks_default_variant(client: TestClient, chime_dir: Path) -> None:
    """`default.*` juga dianggap chime default; hasil diurutkan berdasarkan nama file."""
    chime_dir.mkdir(parents=True)
    (chime_dir / "zebra.wav").write_bytes(b"RIFF")
    (chime_dir / "default.mp3").write_bytes(b"ID3")

    response = client.get("/chimes")
    body = response.json()
    assert [chime["id"] for chime in body["chimes"]] == ["default", "zebra"]
    default_entry = next(chime for chime in body["chimes"] if chime["id"] == "default")
    assert default_entry["is_default"] is True
    assert body["default_chime"] == "chime/default.mp3"


def test_list_chimes_no_default_when_unmarked(client: TestClient, chime_dir: Path) -> None:
    """Tanpa file `chime.*`/`default.*`, tidak ada chime default (default_chime=None)."""
    chime_dir.mkdir(parents=True)
    (chime_dir / "bel_masuk.wav").write_bytes(b"RIFF")
    response = client.get("/chimes")
    body = response.json()
    assert body["count"] == 1
    assert body["chimes"][0]["is_default"] is False
    assert body["default_chime"] is None


# --- ChimeCatalog (unit) ------------------------------------------------------


async def test_catalog_chime_dir_outside_sounds_dir_falls_back_to_filename(tmp_path: Path) -> None:
    """chime_dir di luar sounds_dir (konfigurasi user) → `file` tetap relatif (nama file saja)."""
    sounds_dir = tmp_path / "sounds"
    chime_dir = tmp_path / "chime_terpisah"
    chime_dir.mkdir(parents=True)
    (chime_dir / "ding.wav").write_bytes(b"RIFF")

    catalog = ChimeCatalog(AnnouncementConfig(sounds_dir=str(sounds_dir), chime_dir=str(chime_dir)))
    profiles = await catalog.list()
    assert len(profiles) == 1
    assert profiles[0].id == "ding"
    assert profiles[0].file == "ding.wav"

