"""Create/edit dialog for a Client. Deliberately minimal — not a CRM."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
)

from app.database.session import session_scope
from app.models import Client
from app.services.client_service import create_client, update_client
from app.ui.errors import run_guarded


class ClientDialog(QDialog):
    def __init__(self, parent=None, *, client_id: int | None = None) -> None:
        super().__init__(parent)
        self._client_id = client_id
        self.setWindowTitle("Edit Client" if client_id else "New Client")
        self.setMinimumWidth(420)

        self._name = QLineEdit()
        self._contact_name = QLineEdit()
        self._contact_email = QLineEdit()
        self._contact_phone = QLineEdit()
        self._address = QPlainTextEdit()
        self._address.setFixedHeight(60)
        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(60)

        form = QFormLayout(self)
        form.addRow("Client / Company Name *", self._name)
        form.addRow("Contact Name", self._contact_name)
        form.addRow("Email", self._contact_email)
        form.addRow("Phone", self._contact_phone)
        form.addRow("Address", self._address)
        form.addRow("Notes", self._notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if client_id is not None:
            self._load(client_id)

    def _load(self, client_id: int) -> None:
        with session_scope() as session:
            client = session.get(Client, client_id)
            if client is None:
                return
            self._name.setText(client.name)
            self._contact_name.setText(client.contact_name or "")
            self._contact_email.setText(client.contact_email or "")
            self._contact_phone.setText(client.contact_phone or "")
            self._address.setPlainText(client.address or "")
            self._notes.setPlainText(client.notes or "")

    def _on_save(self) -> None:
        def _save():
            with session_scope() as session:
                if self._client_id is None:
                    create_client(
                        session,
                        name=self._name.text(),
                        contact_name=self._contact_name.text(),
                        contact_email=self._contact_email.text(),
                        contact_phone=self._contact_phone.text(),
                        address=self._address.toPlainText(),
                        notes=self._notes.toPlainText(),
                    )
                else:
                    client = session.get(Client, self._client_id)
                    update_client(
                        session,
                        client,
                        name=self._name.text(),
                        contact_name=self._contact_name.text(),
                        contact_email=self._contact_email.text(),
                        contact_phone=self._contact_phone.text(),
                        address=self._address.toPlainText(),
                        notes=self._notes.toPlainText(),
                    )
            return True

        result = run_guarded(self, _save, context="saving client")
        if result:
            self.accept()
