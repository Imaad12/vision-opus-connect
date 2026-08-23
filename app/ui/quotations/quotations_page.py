"""Quotations: every quotation revision across every project.

Visually distinguishes DRAFT/SUBMITTED (not yet a commitment) from WON
(awarded — the only status that ever becomes contract revenue) and
LOST/WITHDRAWN, so nothing here is ever mistaken for awarded revenue.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.database.session import session_scope
from app.models import QuotationVersion
from app.services.quotation_service import list_quotation_versions, mark_awarded, mark_lost, mark_submitted
from app.ui.errors import run_guarded
from app.ui.formatting import format_date, format_money
from app.ui.widgets.sortable_items import ValueSortItem

COLUMNS = ["Quotation Number", "Revision", "Date", "Project", "Client", "Status", "Quoted Value"]

_STATUS_NOTE = (
    "A quotation is not an awarded project. Only WON quotations set a contract value; "
    "everything else here is a proposal, not revenue."
)


class QuotationsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel("Quotations")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)
        new_button = QPushButton("+ New Quotation")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._create_quotation)
        header_row.addWidget(new_button)
        layout.addLayout(header_row)

        note = QLabel(_STATUS_NOTE)
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by quotation number or project…")
        self._search.textChanged.connect(self.refresh)
        layout.addWidget(self._search)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self._table, 1)

        actions_row = QHBoxLayout()
        actions_row.addStretch(1)
        submit_button = QPushButton("Mark Submitted")
        submit_button.clicked.connect(self._mark_submitted)
        lost_button = QPushButton("Mark Lost")
        lost_button.clicked.connect(self._mark_lost)
        award_button = QPushButton("Mark Awarded…")
        award_button.setObjectName("primaryButton")
        award_button.clicked.connect(self._mark_awarded)
        for button in (submit_button, lost_button, award_button):
            actions_row.addWidget(button)
        layout.addLayout(actions_row)

    def refresh(self) -> None:
        search = self._search.text().strip() or None

        def _load():
            with session_scope() as session:
                return list_quotation_versions(session, search=search)

        versions = run_guarded(self, _load, context="loading quotations")
        if versions is None:
            return

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(versions))
        for row, version in enumerate(versions):
            quotation = version.quotation
            project = quotation.project
            values = [
                (quotation.reference_number or "—", None),
                (str(version.version_number), version.version_number),
                (format_date(version.issued_date), version.issued_date),
                (project.name, None),
                (project.client.name if project.client else "—", None),
                (version.status.value.title(), None),
                (format_money(version.quoted_value, version.currency), version.quoted_value),
            ]
            for col, (text, sort_value) in enumerate(values):
                item = ValueSortItem(text, sort_value)
                if col == 0:
                    item.setData(Qt.UserRole, version.id)
                self._table.setItem(row, col, item)
        self._table.setSortingEnabled(True)

    def _create_quotation(self) -> None:
        from app.ui.widgets.project_picker import ProjectPickerDialog

        picker = ProjectPickerDialog(self, title="Select Project for New Quotation")
        if not picker.exec():
            return
        project_id = picker.selected_project_id()
        if project_id is None:
            QMessageBox.information(self, "No projects", "Create a project first.")
            return

        def _load_project():
            with session_scope() as session:
                from app.models import Project

                return session.get(Project, project_id)

        project = run_guarded(self, _load_project, context="loading project")
        if project is None:
            return

        from app.ui.quotations.quotation_dialog import QuotationDialog

        if QuotationDialog(self, project=project).exec():
            self.refresh()

    def _selected_version_id(self) -> int | None:
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a quotation", "Select a quotation row first.")
            return None
        return self._table.item(row, 0).data(Qt.UserRole)

    def _mark_submitted(self) -> None:
        version_id = self._selected_version_id()
        if version_id is None:
            return

        def _apply():
            with session_scope() as session:
                mark_submitted(session, session.get(QuotationVersion, version_id))
            return True

        if run_guarded(self, _apply, context="marking quotation submitted"):
            self.refresh()

    def _mark_lost(self) -> None:
        version_id = self._selected_version_id()
        if version_id is None:
            return

        def _apply():
            with session_scope() as session:
                mark_lost(session, session.get(QuotationVersion, version_id))
            return True

        if run_guarded(self, _apply, context="marking quotation lost"):
            self.refresh()

    def _mark_awarded(self) -> None:
        version_id = self._selected_version_id()
        if version_id is None:
            return

        def _load_currency():
            with session_scope() as session:
                return session.get(QuotationVersion, version_id).currency.value

        currency_label = run_guarded(self, _load_currency, context="loading quotation currency")
        if currency_label is None:
            return

        from app.ui.quotations.quotation_dialog import AwardDialog

        dialog = AwardDialog(self, currency_label=currency_label)
        if not dialog.exec():
            return
        contract_value = dialog.contract_value()

        def _award():
            with session_scope() as session:
                mark_awarded(session, session.get(QuotationVersion, version_id), contract_value=contract_value)
            return True

        if run_guarded(self, _award, context="awarding quotation"):
            self.refresh()
