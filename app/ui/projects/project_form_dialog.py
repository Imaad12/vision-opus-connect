"""Create/edit dialog for a Project.

No financial fields appear here (quoted/awarded/estimated/actual values):
those only ever get set through quotations, awards, and cost entry — never
as defaults typed into a project form. See `app.services.project_service`
for validation.
"""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
)

from app.core.enums import Currency, ProjectStatus
from app.database.session import session_scope
from app.models import Project
from app.services.project_service import create_project, get_project, update_project
from app.ui.errors import run_guarded
from app.ui.widgets.client_selector import ClientSelector


def _to_qdate(value) -> QDate:
    return QDate(value.year, value.month, value.day) if value else QDate()


def _from_qdate(value: QDate):
    return value.toPython() if value.isValid() else None


class ProjectFormDialog(QDialog):
    def __init__(self, parent=None, *, project_id: int | None = None) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self.created_project_id: int | None = None
        self.setWindowTitle("Edit Project" if project_id else "New Project")
        self.setMinimumWidth(460)

        self._project_code = QLineEdit()
        self._project_code.setPlaceholderText("e.g. PRJ-2026-014 (optional, must be unique)")
        self._name = QLineEdit()
        self._client_selector = ClientSelector()
        self._description = QPlainTextEdit()
        self._description.setFixedHeight(60)
        self._status = QComboBox()
        for status in ProjectStatus:
            self._status.addItem(status.value.replace("_", " ").title(), status)
        self._currency = QComboBox()
        for currency in Currency:
            self._currency.addItem(currency.value, currency)
        self._currency.setCurrentText(Currency.AED.value)

        self._start_date = QDateEdit(calendarPopup=True)
        self._start_date.setSpecialValueText(" ")
        self._start_date.setDate(QDate())
        self._planned_completion_date = QDateEdit(calendarPopup=True)
        self._planned_completion_date.setSpecialValueText(" ")
        self._planned_completion_date.setDate(QDate())
        self._actual_completion_date = QDateEdit(calendarPopup=True)
        self._actual_completion_date.setSpecialValueText(" ")
        self._actual_completion_date.setDate(QDate())
        for date_edit in (self._start_date, self._planned_completion_date, self._actual_completion_date):
            date_edit.setMinimumDate(QDate(2000, 1, 1))
            date_edit.setDate(date_edit.minimumDate())

        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(60)

        form = QFormLayout(self)
        form.addRow("Project Number", self._project_code)
        form.addRow("Project Name *", self._name)
        form.addRow("Client *", self._client_selector)
        form.addRow("Description", self._description)
        form.addRow("Status", self._status)
        form.addRow("Currency", self._currency)
        form.addRow("Start Date", self._start_date)
        form.addRow("Expected Completion Date", self._planned_completion_date)
        form.addRow("Actual Completion Date", self._actual_completion_date)
        form.addRow("Notes", self._notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if project_id is not None:
            self._load(project_id)

    def _load(self, project_id: int) -> None:
        with session_scope() as session:
            project = get_project(session, project_id)
            if project is None:
                return
            self._project_code.setText(project.project_code or "")
            self._name.setText(project.name)
            self._client_selector.set_selected_client_id(project.client_id)
            self._description.setPlainText(project.description or "")
            self._status.setCurrentIndex(self._status.findData(project.status))
            self._currency.setCurrentIndex(self._currency.findData(project.contract_currency))
            if project.start_date:
                self._start_date.setDate(_to_qdate(project.start_date))
            if project.planned_completion_date:
                self._planned_completion_date.setDate(_to_qdate(project.planned_completion_date))
            if project.actual_completion_date:
                self._actual_completion_date.setDate(_to_qdate(project.actual_completion_date))
            self._notes.setPlainText(project.notes or "")

    def _optional_date(self, date_edit: QDateEdit):
        return None if date_edit.date() == date_edit.minimumDate() else _from_qdate(date_edit.date())

    def _on_save(self) -> None:
        def _save():
            with session_scope() as session:
                kwargs = dict(
                    name=self._name.text(),
                    client_id=self._client_selector.selected_client_id(),
                    project_code=self._project_code.text(),
                    description=self._description.toPlainText(),
                    status=self._status.currentData(),
                    currency=self._currency.currentData(),
                    start_date=self._optional_date(self._start_date),
                    planned_completion_date=self._optional_date(self._planned_completion_date),
                    actual_completion_date=self._optional_date(self._actual_completion_date),
                    notes=self._notes.toPlainText(),
                )
                if self._project_id is None:
                    project = create_project(session, **kwargs)
                else:
                    project = update_project(session, session.get(Project, self._project_id), **kwargs)
                return project.id

        project_id = run_guarded(self, _save, context="saving project")
        if project_id is not None:
            self.created_project_id = project_id
            self.accept()
