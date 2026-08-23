"""Clients management: list, create, edit. Reached from Settings — see
UI_ARCHITECTURE.md for why this isn't in the primary sidebar nav."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.database.session import session_scope
from app.services.client_service import list_clients
from app.ui.errors import run_guarded

COLUMNS = ["Name", "Contact", "Email", "Phone"]


class ClientsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        title = QLabel("Clients")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)
        new_button = QPushButton("+ New Client")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._create_client)
        header_row.addWidget(new_button)
        layout.addLayout(header_row)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search clients…")
        self._search.textChanged.connect(self.refresh)
        layout.addWidget(self._search)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self._table, 1)

    def refresh(self) -> None:
        def _load():
            with session_scope() as session:
                return list_clients(session, search=self._search.text().strip() or None)

        clients = run_guarded(self, _load, context="loading clients")
        if clients is None:
            return

        self._table.setRowCount(len(clients))
        for row, client in enumerate(clients):
            self._table.setItem(row, 0, QTableWidgetItem(client.name))
            self._table.setItem(row, 1, QTableWidgetItem(client.contact_name or ""))
            self._table.setItem(row, 2, QTableWidgetItem(client.contact_email or ""))
            self._table.setItem(row, 3, QTableWidgetItem(client.contact_phone or ""))
            self._table.item(row, 0).setData(Qt.UserRole, client.id)

    def _create_client(self) -> None:
        from app.ui.clients.client_dialog import ClientDialog

        if ClientDialog(self).exec():
            self.refresh()

    def _edit_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        client_id = self._table.item(row, 0).data(Qt.UserRole)
        from app.ui.clients.client_dialog import ClientDialog

        if ClientDialog(self, client_id=client_id).exec():
            self.refresh()
