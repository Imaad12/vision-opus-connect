"""Entry point for the placeholder desktop shell: `python -m app.ui.main`."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.database.init_db import create_all
from app.ui.main_window import MainWindow


def main() -> int:
    create_all()  # no-op if the database file and tables already exist
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
