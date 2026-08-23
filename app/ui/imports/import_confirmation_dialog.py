"""The explicit "are you sure" step before any business record is created
from an import (Phase 4 brief §18): a plain summary of exactly what will
happen, then CONFIRM IMPORT / REJECT / GO BACK. This dialog never computes
or edits candidate data — it only calls `import_service.confirm_import`
(and, if the user chooses, `reject_import`) with the choices already made
on the review screen.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.database.session import session_scope
from app.services.import_service import confirm_import, get_imported_document, reject_import
from app.ui.errors import run_guarded
from app.ui.formatting import format_money


class ImportConfirmationDialog(QDialog):
    def __init__(
        self,
        document_id: int,
        *,
        client_id: int | None,
        new_client_name: str | None,
        project_id: int | None,
        quotation_id: int | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._document_id = document_id
        self._client_id = client_id
        self._new_client_name = new_client_name
        self._project_id = project_id
        self._quotation_id = quotation_id
        self.setWindowTitle("Confirm Import")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        with session_scope() as session:
            document = get_imported_document(session, document_id)
            candidate = document.quotation_candidate
            client_name = (
                document.resulting_client.name
                if document.resulting_client
                else self._lookup_client_name(session, client_id, new_client_name)
            )
            project_name = self._lookup_project_name(session, project_id)
            boq_count = len(document.boq_line_candidates)
            summary = {
                "client": client_name or "(not selected)",
                "project": project_name or "(not selected)",
                "quotation_number": candidate.quotation_number if candidate else None,
                "net_value": candidate.net_value if candidate else None,
                "tax_value": candidate.tax_value if candidate else None,
                "currency": candidate.currency if candidate else None,
            }

        form = QFormLayout()
        form.addRow("Client", QLabel(summary["client"]))
        form.addRow("Project", QLabel(summary["project"]))
        form.addRow("Quotation Number", QLabel(summary["quotation_number"] or "(none extracted)"))
        form.addRow("Quotation Value", QLabel(format_money(summary["net_value"], summary["currency"])))
        form.addRow("VAT", QLabel(format_money(summary["tax_value"], summary["currency"])))
        form.addRow("Currency", QLabel(summary["currency"] or "—"))
        form.addRow("BOQ Line Count", QLabel(str(boq_count)))
        layout.addLayout(form)

        note = QLabel(
            "This will create or update the client/project/quotation records shown above. "
            "It never marks this project as awarded and never records actual cost or profit — "
            "those still require separate, explicit steps."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        confirm_button = QPushButton("Confirm Import")
        confirm_button.setObjectName("primaryButton")
        confirm_button.clicked.connect(self._confirm)
        reject_button = QPushButton("Reject")
        reject_button.setObjectName("dangerButton")
        reject_button.clicked.connect(self._reject)
        back_button = QPushButton("Go Back")
        back_button.clicked.connect(self.reject)
        buttons.addWidget(confirm_button)
        buttons.addWidget(reject_button)
        buttons.addStretch(1)
        buttons.addWidget(back_button)
        layout.addLayout(buttons)

    @staticmethod
    def _lookup_client_name(session, client_id, new_client_name):
        if new_client_name:
            return new_client_name
        if client_id is None:
            return None
        from app.services.client_service import get_client

        client = get_client(session, client_id)
        return client.name if client else None

    @staticmethod
    def _lookup_project_name(session, project_id):
        if project_id is None:
            return None
        from app.services.project_service import get_project

        project = get_project(session, project_id)
        return project.name if project else None

    def _confirm(self) -> None:
        def _do_confirm() -> bool:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                confirm_import(
                    session,
                    document,
                    client_id=self._client_id,
                    new_client_name=self._new_client_name,
                    project_id=self._project_id,
                    quotation_id=self._quotation_id,
                )
            return True

        if run_guarded(self, _do_confirm, context="confirming import"):
            self.accept()

    def _reject(self) -> None:
        def _do_reject() -> bool:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                reject_import(session, document)
            return True

        if run_guarded(self, _do_reject, context="rejecting import"):
            self.accept()
