"""A client dropdown with an inline "+" to create a new client without
leaving the current form (e.g. project creation) — clients are required
data, not an afterthought."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

from app.database.session import session_scope
from app.services.client_service import list_clients


class ClientSelector(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(220)
        add_button = QPushButton("+ New Client")
        add_button.clicked.connect(self._add_client)

        layout.addWidget(self.combo, 1)
        layout.addWidget(add_button)

        self.reload()

    def reload(self, *, select_client_id: int | None = None) -> None:
        current = select_client_id if select_client_id is not None else self.selected_client_id()
        self.combo.clear()
        # A placeholder with data=None so this widget never defaults to an
        # arbitrary real client when no explicit match/selection is made —
        # Qt's QComboBox otherwise auto-selects the first added item, which
        # would silently point "no selection" at a real (and likely wrong)
        # client the moment any client exists.
        self.combo.addItem("— Select Client —", None)
        with session_scope() as session:
            for client in list_clients(session):
                self.combo.addItem(client.name, client.id)
        if current is not None:
            index = self.combo.findData(current)
            if index >= 0:
                self.combo.setCurrentIndex(index)

    def selected_client_id(self) -> int | None:
        return self.combo.currentData()

    def set_selected_client_id(self, client_id: int | None) -> None:
        if client_id is None:
            return
        index = self.combo.findData(client_id)
        if index >= 0:
            self.combo.setCurrentIndex(index)

    def _add_client(self) -> None:
        from app.ui.clients.client_dialog import ClientDialog

        dialog = ClientDialog(self)
        if dialog.exec():
            with session_scope() as session:
                clients = list_clients(session)
            if clients:
                newest = max(clients, key=lambda c: c.id)
                self.reload(select_client_id=newest.id)
