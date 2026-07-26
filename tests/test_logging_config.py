"""Unit test untuk build_logging_config (Phase 11 — Monitoring).

Murni memeriksa STRUKTUR dict konfigurasi yang dihasilkan (tidak benar-benar
memanggil ``logging.config.dictConfig`` — itu mengubah state logging global
yang bisa mengganggu test lain) — pola yang sama seperti alasan
``build_logging_config`` dipisah dari ``setup_logging`` sejak awal.
"""

from __future__ import annotations

from pathlib import Path

from announcement_server.core.config import LoggingConfig
from announcement_server.core.logging import build_logging_config


def test_default_filenames() -> None:
    config = LoggingConfig()
    assert config.error_filename == "error.log"
    assert config.playback_filename == "playback.log"
    assert config.worker_filename == "worker.log"


def test_creates_four_rotating_handlers(tmp_path: Path) -> None:
    config = LoggingConfig(directory=str(tmp_path))
    result = build_logging_config(config)

    handlers = result["handlers"]
    assert set(handlers.keys()) == {"console", "rotating_file", "error_file", "playback_file", "worker_file"}
    for name in ("rotating_file", "error_file", "playback_file", "worker_file"):
        assert handlers[name]["class"] == "logging.handlers.RotatingFileHandler"
        assert handlers[name]["maxBytes"] == config.max_bytes
        assert handlers[name]["backupCount"] == config.backup_count


def test_error_file_handler_level_is_error_regardless_of_global_level(tmp_path: Path) -> None:
    config = LoggingConfig(directory=str(tmp_path), level="DEBUG")
    result = build_logging_config(config)
    assert result["handlers"]["error_file"]["level"] == "ERROR"


def test_error_file_attached_to_root_for_global_error_capture(tmp_path: Path) -> None:
    config = LoggingConfig(directory=str(tmp_path))
    result = build_logging_config(config)
    assert "error_file" in result["root"]["handlers"]


def test_playback_logger_routes_to_playback_file(tmp_path: Path) -> None:
    config = LoggingConfig(directory=str(tmp_path))
    result = build_logging_config(config)
    playback_logger = result["loggers"]["announcement_server.playback"]
    assert playback_logger["handlers"] == ["playback_file"]


def test_worker_logger_routes_to_worker_file(tmp_path: Path) -> None:
    config = LoggingConfig(directory=str(tmp_path))
    result = build_logging_config(config)
    worker_logger = result["loggers"]["announcement_server.queueing"]
    assert worker_logger["handlers"] == ["worker_file"]


def test_playback_and_worker_loggers_still_propagate_to_root(tmp_path: Path) -> None:
    """Log Playback/Worker HARUS tetap juga muncul di file utama & error_file (lewat root) —
    file khusus (Phase 11) adalah salinan TERFOKUS, bukan pengganti file utama."""
    config = LoggingConfig(directory=str(tmp_path))
    result = build_logging_config(config)
    assert result["loggers"]["announcement_server.playback"].get("propagate", True) is True
    assert result["loggers"]["announcement_server.queueing"].get("propagate", True) is True


def test_custom_filenames_are_respected(tmp_path: Path) -> None:
    config = LoggingConfig(
        directory=str(tmp_path),
        error_filename="custom_error.log",
        playback_filename="custom_playback.log",
        worker_filename="custom_worker.log",
    )
    result = build_logging_config(config)
    assert result["handlers"]["error_file"]["filename"] == str(tmp_path / "custom_error.log")
    assert result["handlers"]["playback_file"]["filename"] == str(tmp_path / "custom_playback.log")
    assert result["handlers"]["worker_file"]["filename"] == str(tmp_path / "custom_worker.log")


def test_setup_logging_actually_applies_without_error(tmp_path: Path) -> None:
    """Satu test integrasi ringan: `setup_logging` benar-benar bisa dipanggil tanpa error
    (dictConfig valid) dan seluruh file log ter-buat di disk."""
    import logging

    from announcement_server.core.logging import setup_logging

    config = LoggingConfig(directory=str(tmp_path))
    setup_logging(config)

    logging.getLogger("announcement_server.playback.manager").info("test playback log")
    logging.getLogger("announcement_server.queueing.worker").info("test worker log")
    logging.getLogger("announcement_server.somewhere").error("test error log")

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert (tmp_path / config.filename).exists()
    assert (tmp_path / config.playback_filename).exists()
    assert (tmp_path / config.worker_filename).exists()
    assert (tmp_path / config.error_filename).exists()
