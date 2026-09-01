"""The explicit "are you sure" step before any business record is created
from an import (Phase 4 brief §18): a plain summary of exactly what will
happen, then CONFIRM IMPORT / REJECT / GO BACK. This dialog never computes
or edits candidate data — it only calls `import_service.confirm_import`
(and, if the user chooses, `reject_import`) with the choices already made
on the review screen.

Confirming as a revision of an existing quotation can additionally raise
`RevisionConflictError` (incoming date earlier than, or tied with a
differing total to, the existing quotation's current version) — see
`_confirm`. That is handled here rather than via the generic
`app.ui.errors.run_guarded` helper specifically so a reviewer can be shown
the conflict and asked to explicitly decide, rather than just being told
"blocked." The default, every time, is blocked; only an explicit "yes" on
that prompt re-attempts confirmation with the acknowledgement set.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import session_scope
from app.services.errors import RevisionConflictError, ValidationError
from app.services.import_service import confirm_import, get_imported_document, reject_import
from app.ui.errors import run_guarded, show_database_error, show_unexpected_error, show_validation_error
from app.ui.formatting import format_money
from app.ui.logging_setup import get_logger

logger = get_logger("ui.imports.import_confirmation_dialog")


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
        segment_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._document_id = document_id
        self._segment_id = segment_id
        self._client_id = client_id
        self._new_client_name = new_client_name
        self._project_id = project_id
        self._quotation_id = quotation_id
        self.setWindowTitle("Confirm Import")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        with session_scope() as session:
            document = get_imported_document(session, document_id)
            segment = next((s for s in document.segments if s.id == segment_id), None) if segment_id is not None else None
            candidate = segment.quotation_candidate if segment is not None else document.quotation_candidate
            client_name = (
                document.resulting_client.name
                if document.resulting_client
                else self._lookup_client_name(session, client_id, new_client_name)
            )
            project_name = self._lookup_project_name(session, project_id)
            boq_count = len(segment.boq_line_candidates) if segment is not None else len(document.boq_line_candidates)
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
        self._attempt_confirm(acknowledge_revision_conflict=False)

    def _attempt_confirm(self, *, acknowledge_revision_conflict: bool) -> None:
        def _do_confirm() -> bool:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                segment = (
                    next((s for s in document.segments if s.id == self._segment_id), None)
                    if self._segment_id is not None
                    else None
                )
                confirm_import(
                    session,
                    document,
                    segment=segment,
                    client_id=self._client_id,
                    new_client_name=self._new_client_name,
                    project_id=self._project_id,
                    quotation_id=self._quotation_id,
                    acknowledge_revision_conflict=acknowledge_revision_conflict,
                )
            return True

        try:
            succeeded = _do_confirm()
        except RevisionConflictError as exc:
            if self._prompt_revision_conflict(exc):
                self._attempt_confirm(acknowledge_revision_conflict=True)
            return
        except ValidationError as exc:
            show_validation_error(self, str(exc))
            return
        except SQLAlchemyError:
            logger.exception("Database error while confirming import")
            show_database_error(self)
            return
        except Exception:
            logger.exception("Unexpected error while confirming import")
            show_unexpected_error(self)
            return

        if succeeded:
            self.accept()

    def _prompt_revision_conflict(self, exc: RevisionConflictError) -> bool:
        """Show the conflict plainly and require an explicit yes/no —
        blocked stays the default (No is the default button; closing the
        dialog also counts as "No"). Returns True only if the reviewer
        explicitly chose to proceed anyway."""
        reply = QMessageBox.warning(
            self,
            "Revision conflict",
            f"{exc}\n\nProceed and add this as a new revision anyway?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _reject(self) -> None:
        def _do_reject() -> bool:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                segment = (
                    next((s for s in document.segments if s.id == self._segment_id), None)
                    if self._segment_id is not None
                    else None
                )
                reject_import(session, document, segment=segment)
            return True

        if run_guarded(self, _do_reject, context="rejecting import"):
            self.accept()
