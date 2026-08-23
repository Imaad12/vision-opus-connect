"""Minimal application shell.

This is a placeholder proving the architectural seam (UI -> services ->
database) works end to end. It is not the product UI, which will be built
in a later phase. Note that this module contains no SQLAlchemy imports and
no business logic of its own — it only calls into `app.services`.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from app.database.session import session_scope
from app.services.project_service import count_active_projects


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vision Contracting — Profit System (Phase 1 shell)")
        self.resize(480, 200)

        self._status_label = QLabel("Loading...")
        refresh_button = QPushButton("Refresh project count")
        refresh_button.clicked.connect(self._refresh_project_count)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("This is a placeholder shell for architecture verification."))
        layout.addWidget(self._status_label)
        layout.addWidget(refresh_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._refresh_project_count()

    def _refresh_project_count(self) -> None:
        with session_scope() as session:
            count = count_active_projects(session)
        self._status_label.setText(f"Active projects in database: {count}")
