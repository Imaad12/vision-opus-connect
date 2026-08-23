"""Application logging.

A single place that configures logging for the desktop app: a rotating
file under the user's local app-data directory, plus console output for
`python -m app.ui.main` during development. Never logs financial amounts,
secrets, or credentials — only enough context (entity ids, exception
types) to diagnose a problem, per the project's logging policy.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from app.core.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "app.log"

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("app")
    root.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"app.{name}")


__all__ = ["configure_logging", "get_logger", "LOG_FILE"]
