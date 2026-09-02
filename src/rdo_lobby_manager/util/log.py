"""Logging setup — single source of truth for the app's logger."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rdo_lobby_manager.config.paths import log_file

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once. Idempotent — safe to call multiple times."""
    global _configured  # noqa: PLW0603  -- module-level state, intentional
    if _configured:
        return

    log_path: Path = log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # File handler: everything at INFO+, keeps history
    file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    # Stream handler: WARNING+ to stderr (so it shows in terminal/console)
    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()  # dedupe if imported twice
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # Tame noisy third-party loggers
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger for `name` (typically __name__). Configures on first call."""
    setup_logging()
    return logging.getLogger(name)
