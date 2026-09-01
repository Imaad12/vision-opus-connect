"""Entry point for the desktop application: `python -m app.ui.main`."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.database.init_db import create_all
from app.database.seed import seed_default_cost_categories
from app.database.session import session_scope
from app.ui.logging_setup import configure_logging, get_logger
from app.ui.main_window import MainWindow
from app.ui.style import STYLESHEET

logger = get_logger("main")


def _ensure_reference_data() -> None:
    """Cost categories are reference/lookup data the app needs to function
    (the cost-entry forms have nothing to offer in their category selector
    otherwise) — not sample business data, so seeding them on startup is
    safe and always idempotent. This never inserts a project, client, or
    any financial figure."""
    with session_scope() as session:
        seed_default_cost_categories(session)


def main() -> int:
    configure_logging()
    logger.info("Starting Vision Contracting desktop application")

    create_all()  # no-op if the database file and tables already exist
    _ensure_reference_data()

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
