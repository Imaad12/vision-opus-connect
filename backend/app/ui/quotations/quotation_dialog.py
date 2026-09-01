"""Create a new quotation, add a revision to an existing one, or award it.

The UI never sets `Project.contract_value` directly — only
`quotation_service.mark_awarded` does, and only from here.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QPlainTextEdit

from app.database.session import session_scope
from app.models import Project, Quotation
from app.services.quotation_service import create_quotation, create_quotation_revision
from app.ui.errors import run_guarded
from app.ui.widgets.money_field import MoneyLineEdit


class QuotationDialog(QDialog):
    """New quotation (project given) or a new revision (quotation given)."""

    def __init__(self, parent, *, project: Project | None = None, quotation: Quotation | None = None) -> None:
        super().__init__(parent)
        if not project and not quotation:
            raise ValueError("Provide either a project (new quotation) or a quotation (new revision).")
        self._project = project
        self._quotation = quotation
        is_revision = quotation is not None
        self.setWindowTitle("New Quotation Revision" if is_revision else "New Quotation")
        self.setMinimumWidth(420)

        self._reference_number = QLineEdit()
        self._reference_number.setEnabled(not is_revision)
        if is_revision:
            self._reference_number.setText(quotation.reference_number or "")
        self._title = QLineEdit()
        self._title.setEnabled(not is_revision)
        if is_revision:
            self._title.setText(quotation.title or "")

        self._quoted_value = MoneyLineEdit(placeholder="e.g. 1000000.00")
        self._issued_date = QDateEdit(calendarPopup=True)
        self._issued_date.setDate(QDate.currentDate())
        self._valid_until = QDateEdit(calendarPopup=True)
        self._valid_until.setSpecialValueText(" ")
        self._valid_until.setMinimumDate(QDate(2000, 1, 1))
        self._valid_until.setDate(self._valid_until.minimumDate())
        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(50)

        form = QFormLayout(self)
        form.addRow("Quotation Number", self._reference_number)
        form.addRow("Title", self._title)
        form.addRow("Quoted Value", self._quoted_value)
        form.addRow("Issued Date", self._issued_date)
        form.addRow("Valid Until", self._valid_until)
        form.addRow("Notes", self._notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _optional_valid_until(self):
        if self._valid_until.date() == self._valid_until.minimumDate():
            return None
        return self._valid_until.date().toPython()

    def _on_save(self) -> None:
        def _save():
            currency = self._project.contract_currency if self._project else self._quotation.project.contract_currency
            with session_scope() as session:
                if self._quotation is None:
                    project = session.get(Project, self._project.id)
                    create_quotation(
                        session,
                        project,
                        reference_number=self._reference_number.text(),
                        title=self._title.text(),
                        quoted_value=self._quoted_value.decimal_value(),
                        currency=currency,
                        issued_date=self._issued_date.date().toPython(),
                        valid_until=self._optional_valid_until(),
                        notes=self._notes.toPlainText(),
                    )
                else:
                    quotation = session.get(Quotation, self._quotation.id)
                    create_quotation_revision(
                        session,
                        quotation,
                        quoted_value=self._quoted_value.decimal_value(),
                        currency=currency,
                        issued_date=self._issued_date.date().toPython(),
                        valid_until=self._optional_valid_until(),
                        notes=self._notes.toPlainText(),
                    )
            return True

        if run_guarded(self, _save, context="saving quotation"):
            self.accept()


class AwardDialog(QDialog):
    def __init__(self, parent, *, currency_label: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Award Quotation")
        self.setMinimumWidth(360)

        self._contract_value = MoneyLineEdit(placeholder="required")

        form = QFormLayout(self)
        form.addRow(f"Awarded Contract Value ({currency_label}) *", self._contract_value)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def contract_value(self) -> Decimal | None:
        return self._contract_value.decimal_value()
