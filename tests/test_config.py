"""Unit test untuk core/config.py (Phase 13 — coverage gap-fill).

Fokus pada bagian yang sebelumnya hanya tersentuh TIDAK LANGSUNG lewat
test API/integration: pembacaan YAML, prioritas sumber konfigurasi
(env var > YAML > default), validator, dan caching ``get_settings()``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from announcement_server.core.config import (
    AnnouncementConfig,
    AppSettings,
    LoggingConfig,
    ScheduleDefinition,
    SchedulerConfig,
    TTSConfig,
    ZoneDefinition,
    _read_yaml_file,
    get_settings,
)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- _read_yaml_file -----------------------------------------------------


def test_read_yaml_file_missing_returns_empty_dict(tmp_path: Path) -> None:
    assert _read_yaml_file(tmp_path / "tidak-ada.yaml") == {}


def test_read_yaml_file_empty_file_returns_empty_dict(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("")
    assert _read_yaml_file(path) == {}


def test_read_yaml_file_valid_content(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("server:\n  port: 9999\n")
    assert _read_yaml_file(path) == {"server": {"port": 9999}}


# --- LoggingConfig.validate_level -----------------------------------------------------


def test_logging_level_accepts_valid_values() -> None:
    assert LoggingConfig(level="debug").level == "DEBUG"
    assert LoggingConfig(level="WARNING").level == "WARNING"


def test_logging_level_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="logging.level"):
        LoggingConfig(level="INVALID_LEVEL")


# --- AppSettings: default / YAML / env var priority -----------------------------------------------------


def test_app_settings_defaults_without_yaml_file(tmp_path: Path) -> None:
    settings = AppSettings(yaml_config_path=str(tmp_path / "tidak-ada.yaml"))  # type: ignore[call-arg]
    assert settings.server.port == 8000
    assert settings.queue.max_size == 100
    assert settings.scheduler.timezone == "local"
    assert settings.zones == {}
    assert settings.schedules == {}


def test_app_settings_loads_values_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("server:\n  port: 7000\nqueue:\n  max_size: 42\n")

    settings = AppSettings(yaml_config_path=str(yaml_path))  # type: ignore[call-arg]

    assert settings.server.port == 7000
    assert settings.queue.max_size == 42


def test_env_var_overrides_yaml_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("server:\n  port: 7000\n")
    monkeypatch.setenv("APP_SERVER__PORT", "9000")

    settings = AppSettings(yaml_config_path=str(yaml_path))  # type: ignore[call-arg]

    assert settings.server.port == 9000  # env var menang atas YAML


def test_env_var_wins_over_yaml_even_when_yaml_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("logging:\n  level: ERROR\n")
    monkeypatch.setenv("APP_LOGGING__LEVEL", "DEBUG")

    settings = AppSettings(yaml_config_path=str(yaml_path))  # type: ignore[call-arg]

    assert settings.logging.level == "DEBUG"


def test_app_settings_zones_and_schedules_parsed_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "zones:\n"
        "  lobby:\n"
        "    enabled: false\n"
        "    volume: 0.5\n"
        "schedules:\n"
        "  bell:\n"
        "    recurrence: daily\n"
        "    time_of_day: '07:00'\n"
        "    announcement:\n"
        "      type: tts\n"
        "      text: Halo\n"
    )

    settings = AppSettings(yaml_config_path=str(yaml_path))  # type: ignore[call-arg]

    assert settings.zones["lobby"].enabled is False
    assert settings.zones["lobby"].volume == 0.5
    assert settings.schedules["bell"].recurrence == "daily"
    assert settings.schedules["bell"].announcement.text == "Halo"


def test_app_settings_extra_yaml_keys_are_ignored(tmp_path: Path) -> None:
    """`extra=\"ignore\"` — key YAML yang tidak dikenal tidak boleh membuat AppSettings gagal dibuat."""
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("key_tidak_dikenal: 123\n")
    settings = AppSettings(yaml_config_path=str(yaml_path))  # type: ignore[call-arg]
    assert settings.server.port == 8000  # tetap default, tidak error


# --- get_settings() caching -----------------------------------------------------


def test_get_settings_returns_cached_singleton() -> None:
    first = get_settings()
    second = get_settings()
    assert first is second


def test_get_settings_cache_clear_creates_new_instance() -> None:
    first = get_settings()
    get_settings.cache_clear()
    second = get_settings()
    assert first is not second


# --- Model default lain (Phase 6/7/8) -----------------------------------------------------


def test_zone_definition_defaults() -> None:
    zone = ZoneDefinition(enabled=True)
    assert zone.device_id is None
    assert zone.volume == 1.0


def test_announcement_config_defaults() -> None:
    config = AnnouncementConfig()
    assert config.sounds_dir == "sounds"
    assert config.ffmpeg_binary_path == "ffmpeg"
    assert config.conversion_timeout_seconds == 30.0


def test_tts_config_defaults_engine_is_piper() -> None:
    """RC1-6: menutup celah cakupan -- sebelum ini TIDAK ADA satu pun test yang membuat
    `TTSConfig()` tanpa argumen `engine=` eksplisit (seluruh ~15+ file test lain selalu
    meng-override-nya sendiri). Artinya default field-level ('piper' sebagai engine V1)
    tidak pernah benar-benar dijamin oleh test manapun -- jika default ini tanpa sengaja
    berubah, tidak ada test yang akan gagal. Test ini secara eksplisit mengunci kontrak
    backward-compatibility V1: server yang di-deploy tanpa mengubah `tts.engine` di
    config.yaml HARUS tetap memakai Piper."""
    config = TTSConfig()
    assert config.engine == "piper"
    assert config.additional_engines == []  # V2 Phase 7: opt-in, kosong = perilaku V1/Phase 2-6


def test_scheduler_config_defaults() -> None:
    config = SchedulerConfig()
    assert config.poll_interval_seconds == 5.0
    assert config.timezone == "local"


def test_schedule_definition_requires_recurrence_and_time_of_day() -> None:
    with pytest.raises(ValueError):
        ScheduleDefinition(announcement={"type": "tts", "text": "x"})  # type: ignore[call-arg]


# --- validate_runtime_config (Phase 14) -----------------------------------------------------


def test_validate_runtime_config_creates_missing_directories(tmp_path: Path) -> None:
    from announcement_server.core.config import validate_runtime_config

    settings = AppSettings(
        yaml_config_path=str(tmp_path / "tidak-ada.yaml"),  # type: ignore[call-arg]
        tts={"cache_dir": str(tmp_path / "cache_tts")},
        announcement={"sounds_dir": str(tmp_path / "sounds"), "converted_cache_dir": str(tmp_path / "cache_ann")},
        logging={"directory": str(tmp_path / "logs")},
    )

    validate_runtime_config(settings)  # tidak boleh melempar

    assert (tmp_path / "cache_tts").is_dir()
    assert (tmp_path / "sounds").is_dir()
    assert (tmp_path / "cache_ann").is_dir()
    assert (tmp_path / "logs").is_dir()


def test_validate_runtime_config_raises_configuration_error_when_path_is_a_file(tmp_path: Path) -> None:
    from announcement_server.core.config import validate_runtime_config
    from announcement_server.core.exceptions import ConfigurationError

    blocking_file = tmp_path / "blocked"
    blocking_file.write_text("bukan folder")

    settings = AppSettings(
        yaml_config_path=str(tmp_path / "tidak-ada.yaml"),  # type: ignore[call-arg]
        tts={"cache_dir": str(blocking_file / "cache_tts")},
    )

    with pytest.raises(ConfigurationError):
        validate_runtime_config(settings)
