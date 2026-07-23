"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from announcement_server.core.config import get_settings
from announcement_server.main import create_app


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """TestClient dengan cache settings di-reset agar test saling independen."""
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
