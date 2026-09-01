"""Documents placeholder — Google Drive integration is a later phase."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ProjectDocumentsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        label = QLabel("Google Drive integration will be added in a later phase.")
        label.setObjectName("mutedLabel")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

    def refresh(self) -> None:
        pass
