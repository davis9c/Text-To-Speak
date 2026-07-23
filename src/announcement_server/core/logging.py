"""Konfigurasi logging terpusat.

Menggunakan ``logging.config.dictConfig`` agar mudah diperluas di fase-fase
berikutnya (mis. Playback Log, Worker Log, Error Log terpisah pada Phase 11
- Monitoring) tanpa mengubah cara pemanggilan ``setup_logging()``.
"""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

from announcement_server.core.config import LoggingConfig

_JSON_FORMAT = (
    '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
    '"logger": "%(name)s", "message": "%(message)s"}'
)
_TEXT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def build_logging_config(config: LoggingConfig) -> dict[str, Any]:
    """Membangun dict konfigurasi logging dari LoggingConfig.

    Dipisah dari ``setup_logging`` supaya bisa di-unit-test tanpa efek
    samping (dictConfig langsung mengubah state logging global).
    """
    log_dir = Path(config.directory)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_dir / config.filename
    fmt = _JSON_FORMAT if config.json_format else _TEXT_FORMAT

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": fmt},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": config.level,
            },
            "rotating_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "level": config.level,
                "filename": str(log_file_path),
                "maxBytes": config.max_bytes,
                "backupCount": config.backup_count,
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": config.level,
            "handlers": ["console", "rotating_file"],
        },
        "loggers": {
            "uvicorn": {"level": config.level, "handlers": ["console", "rotating_file"], "propagate": False},
            "uvicorn.error": {"level": config.level, "handlers": ["console", "rotating_file"], "propagate": False},
            "uvicorn.access": {"level": config.level, "handlers": ["console", "rotating_file"], "propagate": False},
        },
    }


def setup_logging(config: LoggingConfig) -> None:
    """Menerapkan konfigurasi logging global. Dipanggil sekali saat startup."""
    logging.config.dictConfig(build_logging_config(config))
    logging.getLogger(__name__).info(
        "Logging berhasil diinisialisasi (level=%s, file=%s)",
        config.level,
        Path(config.directory) / config.filename,
    )
