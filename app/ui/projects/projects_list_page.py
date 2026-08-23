"""Projects list: search, status filter, sort, open a project.

Each row's financial columns come straight from that project's
`ProjectFinancialSnapshot` (via `list_projects_with_snapshots`) — nothing
here recomputes a total or margin.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.enums import ProjectStatus
from app.database.session import session_scope
from app.services.project_service import list_projects_with_snapshots
from app.ui.errors import run_guarded
from app.ui.formatting import format_date, format_money, format_percentage
from app.ui.widgets.sortable_items import ValueSortItem

COLUMNS = [
    "Project Number",
    "Project Name",
    "Client",
    "Status",
    "Quoted Value",
    "Awarded Value",
    "Revised Contract Value",
    "Estimated Cost",
    "Actual Cost",
    "Actual Profit",
    "Actual Margin",
    "Start Date",
    "Completion Date",
]


class ProjectsListPage(QWidget):
    def __init__(self, *, open_project: Callable[[int], None]) -> None:
        super().__init__()
        self._open_project = open_project

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        title = QLabel("Projects")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)
        new_button = QPushButton("+ New Project")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._create_project)
        header_row.addWidget(new_button)
        layout.addLayout(header_row)

        filter_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name, project number, or client…")
        self._search.textChanged.connect(self.refresh)
        self._status_filter = QComboBox()
        self._status_filter.addItem("All Statuses", None)
        for status in ProjectStatus:
            self._status_filter.addItem(status.value.replace("_", " ").title(), status)
        self._status_filter.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self._search, 1)
        filter_row.addWidget(self._status_filter)
        layout.addLayout(filter_row)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self._table, 1)

    def refresh(self) -> None:
        status = self._status_filter.currentData()
        search = self._search.text().strip() or None

        def _load():
            with session_scope() as session:
                return list_projects_with_snapshots(session, search=search, status=status)

        pairs = run_guarded(self, _load, context="loading projects list")
        if pairs is None:
            return

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(pairs))
        for row, (project, snapshot) in enumerate(pairs):
            currency = snapshot.currency
            values = [
                (project.project_code or "—", project.project_code),
                (project.name, project.name),
                (project.client.name if project.client else "—", project.client.name if project.client else ""),
                (project.status.value.replace("_", " ").title(), project.status.value),
                (format_money(snapshot.quoted_value, currency), snapshot.quoted_value),
                (format_money(snapshot.awarded_contract_value, currency), snapshot.awarded_contract_value),
                (format_money(snapshot.revised_contract_value, currency), snapshot.revised_contract_value),
                (format_money(snapshot.estimated_cost, currency), snapshot.estimated_cost),
                (format_money(snapshot.actual_cost, currency), snapshot.actual_cost),
                (format_money(snapshot.actual_profit, currency), snapshot.actual_profit),
                (format_percentage(snapshot.actual_margin), snapshot.actual_margin),
                (format_date(project.start_date), project.start_date),
                (format_date(project.planned_completion_date), project.planned_completion_date),
            ]
            for col, (text, sort_value) in enumerate(values):
                item = ValueSortItem(text, sort_value)
                if col == 0:
                    item.setData(Qt.UserRole, project.id)
                self._table.setItem(row, col, item)
        self._table.setSortingEnabled(True)

    def _open_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        project_id = self._table.item(row, 0).data(Qt.UserRole)
        self._open_project(project_id)

    def _create_project(self) -> None:
        from app.ui.projects.project_form_dialog import ProjectFormDialog

        dialog = ProjectFormDialog(self)
        if dialog.exec():
            self.refresh()
            if dialog.created_project_id is not None:
                self._open_project(dialog.created_project_id)
