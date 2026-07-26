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

    Phase 11 (Monitoring) menambahkan 3 file log terpisah DI LUAR file
    utama (``rotating_file``, tidak diubah) — setiap event tetap masuk ke
    file utama (satu tempat untuk melihat semuanya), DAN juga disalin ke
    file yang lebih spesifik untuk memudahkan troubleshooting per-domain:
    - ``error_file``: seluruh log level ERROR/CRITICAL, dari logger MANA PUN.
    - ``playback_file``: seluruh log dari domain Playback (Phase 4/9).
    - ``worker_file``: seluruh log dari domain Queue Worker/Pipeline (Phase 2/5).
    """
    log_dir = Path(config.directory)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_dir / config.filename
    error_file_path = log_dir / config.error_filename
    playback_file_path = log_dir / config.playback_filename
    worker_file_path = log_dir / config.worker_filename
    fmt = _JSON_FORMAT if config.json_format else _TEXT_FORMAT

    def _rotating_file_handler(path: Path, level: str) -> dict[str, Any]:
        return {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "level": level,
            "filename": str(path),
            "maxBytes": config.max_bytes,
            "backupCount": config.backup_count,
            "encoding": "utf-8",
        }

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
            "rotating_file": _rotating_file_handler(log_file_path, config.level),
            # Phase 11 — Monitoring:
            "error_file": _rotating_file_handler(error_file_path, "ERROR"),
            "playback_file": _rotating_file_handler(playback_file_path, config.level),
            "worker_file": _rotating_file_handler(worker_file_path, config.level),
        },
        "root": {
            # `error_file` dipasang di root supaya menangkap ERROR/CRITICAL
            # dari LOGGER MANA PUN (bukan hanya domain tertentu) — satu
            # tempat untuk melihat seluruh error aplikasi (Phase 11).
            "level": config.level,
            "handlers": ["console", "rotating_file", "error_file"],
        },
        "loggers": {
            "uvicorn": {"level": config.level, "handlers": ["console", "rotating_file"], "propagate": False},
            "uvicorn.error": {"level": config.level, "handlers": ["console", "rotating_file"], "propagate": False},
            "uvicorn.access": {"level": config.level, "handlers": ["console", "rotating_file"], "propagate": False},
            # Phase 11 — Playback Log & Worker Log: `propagate: True` (default)
            # supaya log tsb TETAP juga masuk ke file utama & error_file lewat
            # root, sekaligus punya salinan terfokus di file masing-masing.
            "announcement_server.playback": {"level": config.level, "handlers": ["playback_file"]},
            "announcement_server.queueing": {"level": config.level, "handlers": ["worker_file"]},
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
