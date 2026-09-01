"""Structured stdout logging for the FastAPI process.

Deliberately minimal: a production deployment (systemd, a container
platform, etc.) captures stdout/stderr and ships it wherever logs go --
this just makes each line machine-parseable (key=value pairs) instead of
bare text, and lets the log level be raised/lowered per environment via
`VISION_LOG_LEVEL` without a code change. Not used by the PySide6 desktop
app, which has its own separate `app/ui/logging_setup.py` (a rotating
file log meant for a single end user's machine, not log aggregation).
"""

from __future__ import annotations

import logging

from app.core.config import settings


class _KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = (
            f'time="{self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z")}" '
            f'level={record.levelname} logger={record.name} msg="{record.getMessage()}"'
        )
        if record.exc_info:
            base += f"\n{self.formatException(record.exc_info)}"
        return base


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    handler = logging.StreamHandler()
    handler.setFormatter(_KeyValueFormatter())
    root.handlers = [handler]
