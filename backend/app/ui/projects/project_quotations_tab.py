"""Project-scoped quotations: revisions, submit/lost/award actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import joinedload

from app.database.session import session_scope
from app.models import Project, Quotation, QuotationVersion
from app.services.quotation_service import (
    list_quotations_for_project,
    list_versions_for_quotation,
    mark_awarded,
    mark_lost,
    mark_submitted,
)
from app.ui.errors import run_guarded
from app.ui.formatting import format_date, format_money
from app.ui.widgets.sortable_items import ValueSortItem

COLUMNS = ["Quotation Number", "Revision", "Date", "Status", "Quoted Value"]


class ProjectQuotationsTab(QWidget):
    def __init__(self, project_id: int) -> None:
        super().__init__()
        self._project_id = project_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        actions_row = QHBoxLayout()
        new_quotation_button = QPushButton("+ New Quotation")
        new_quotation_button.setObjectName("primaryButton")
        new_quotation_button.clicked.connect(self._new_quotation)
        new_revision_button = QPushButton("+ New Revision (selected)")
        new_revision_button.clicked.connect(self._new_revision)
        submit_button = QPushButton("Mark Submitted")
        submit_button.clicked.connect(self._mark_submitted)
        lost_button = QPushButton("Mark Lost")
        lost_button.clicked.connect(self._mark_lost)
        award_button = QPushButton("Mark Awarded…")
        award_button.clicked.connect(self._mark_awarded)
        for button in (
            new_quotation_button,
            new_revision_button,
            submit_button,
            lost_button,
            award_button,
        ):
            actions_row.addWidget(button)
        actions_row.addStretch(1)
        layout.addLayout(actions_row)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self._table, 1)

    def refresh(self) -> None:
        def _load():
            with session_scope() as session:
                project = session.get(Project, self._project_id)
                quotations = list_quotations_for_project(session, project.id)
                rows = []
                for quotation in quotations:
                    for version in list_versions_for_quotation(session, quotation.id):
                        rows.append((quotation, version))
                return rows

        rows = run_guarded(self, _load, context="loading project quotations")
        if rows is None:
            return

        self._table.setRowCount(len(rows))
        for row, (quotation, version) in enumerate(rows):
            values = [
                (quotation.reference_number or "—", None),
                (str(version.version_number), version.version_number),
                (format_date(version.issued_date), version.issued_date),
                (version.status.value.title(), None),
                (format_money(version.quoted_value, version.currency), version.quoted_value),
            ]
            for col, (text, sort_value) in enumerate(values):
                item = ValueSortItem(text, sort_value)
                if col == 0:
                    item.setData(Qt.UserRole, (quotation.id, version.id))
                self._table.setItem(row, col, item)

    def _selected_ids(self) -> tuple[int, int] | None:
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a quotation", "Select a quotation revision first.")
            return None
        return self._table.item(row, 0).data(Qt.UserRole)

    def _new_quotation(self) -> None:
        from app.ui.quotations.quotation_dialog import QuotationDialog

        def _load_project():
            with session_scope() as session:
                return session.get(Project, self._project_id)

        project = run_guarded(self, _load_project, context="loading project")
        if project is None:
            return
        if QuotationDialog(self, project=project).exec():
            self.refresh()

    def _new_revision(self) -> None:
        ids = self._selected_ids()
        if ids is None:
            return
        quotation_id, _ = ids

        def _load_quotation():
            with session_scope() as session:
                return session.get(Quotation, quotation_id, options=[joinedload(Quotation.project)])

        quotation = run_guarded(self, _load_quotation, context="loading quotation")
        if quotation is None:
            return

        from app.ui.quotations.quotation_dialog import QuotationDialog

        if QuotationDialog(self, quotation=quotation).exec():
            self.refresh()

    def _mark_submitted(self) -> None:
        ids = self._selected_ids()
        if ids is None:
            return
        _, version_id = ids

        def _apply():
            with session_scope() as session:
                mark_submitted(session, session.get(QuotationVersion, version_id))
            return True

        if run_guarded(self, _apply, context="marking quotation submitted"):
            self.refresh()

    def _mark_lost(self) -> None:
        ids = self._selected_ids()
        if ids is None:
            return
        _, version_id = ids

        def _apply():
            with session_scope() as session:
                mark_lost(session, session.get(QuotationVersion, version_id))
            return True

        if run_guarded(self, _apply, context="marking quotation lost"):
            self.refresh()

    def _mark_awarded(self) -> None:
        ids = self._selected_ids()
        if ids is None:
            return
        _, version_id = ids

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
