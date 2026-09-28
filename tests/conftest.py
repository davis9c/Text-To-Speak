"""Shared pytest fixtures & test helpers."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from announcement_server.core.config import get_settings
from announcement_server.main import create_app


def make_fake_executable(script_source: str, name: str, target_dir: Path) -> Path:
    """Membuat fake executable (script Python) yang portabel lintas platform.

    Dipakai oleh test engine (Piper/eSpeak) & asset resolver (ffmpeg) untuk
    menggantikan binary asli yang tidak tersedia di lingkungan test. Di Unix
    script langsung dijalankan via shebang (``#!...``); di Windows, CreateProcess
    tidak bisa mengeksekusi script Python (WinError 193), sehingga dibuat
    wrapper ``.cmd`` yang memanggil ``sys.executable`` dengan script tsb.
    """
    script_path = target_dir / f"{name}.py"
    script_path.write_text(script_source, encoding="utf-8")
    if os.name == "nt":
        wrapper_path = target_dir / f"{name}.cmd"
        wrapper_path.write_text(
            f'@echo off\r\n"{sys.executable}" "{script_path}" %*\r\n',
            encoding="utf-8",
        )
        return wrapper_path
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script_path


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """TestClient dengan cache settings di-reset agar test saling independen."""
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
