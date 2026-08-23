"""Settings: a Phase 3 landing page for administrative areas.

Client management lives here (rather than the primary sidebar) since it is
supporting data, not a primary daily workflow — see UI_ARCHITECTURE.md.
Full application settings (company profile, tax defaults, users) are a
later phase.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class SettingsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Full application settings (company profile, tax defaults, user accounts) "
            "will be added in a later phase."
        )
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        clients_card = QFrame()
        clients_card.setObjectName("card")
        card_layout = QHBoxLayout(clients_card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        text_column = QVBoxLayout()
        heading = QLabel("Clients")
        heading.setObjectName("sectionTitle")
        description = QLabel("Create and edit the clients your projects are awarded by.")
        description.setObjectName("mutedLabel")
        text_column.addWidget(heading)
        text_column.addWidget(description)
        card_layout.addLayout(text_column, 1)
        self._open_clients_button = QPushButton("Manage Clients")
        self._open_clients_button.setObjectName("primaryButton")
        card_layout.addWidget(self._open_clients_button)
        layout.addWidget(clients_card)
        layout.addStretch(1)

    def on_manage_clients(self, callback) -> None:
        self._open_clients_button.clicked.connect(callback)

    def refresh(self) -> None:
        pass
