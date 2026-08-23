"""Estimated Costs tab content.

Shows the CURRENT (latest) revision's lines, editable, plus a read-only
selector to browse Original / previous revisions for comparison — the
mechanism that keeps historical estimates visible without letting them be
edited (see `app.services.cost_service`).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.database.session import session_scope
from app.models import Project
from app.services.cost_service import (
    get_or_create_current_revision,
    list_estimate_revisions,
    list_estimated_costs,
    mark_revision_final,
    remove_estimated_cost_line,
    start_new_estimate_revision,
)
from app.services.financial_service import build_project_financial_snapshot
from app.ui.errors import run_guarded
from app.ui.formatting import format_money, format_percentage, format_quantity
from app.ui.widgets.sortable_items import ValueSortItem

COLUMNS = ["Category", "Description", "Quantity", "Unit", "Unit Rate", "Amount", "Notes"]


class EstimatedCostsWidget(QWidget):
    def __init__(self, project_id: int) -> None:
        super().__init__()
        self._project_id = project_id
        self._revision_ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        summary_row = QHBoxLayout()
        self._total_label = QLabel()
        self._profit_label = QLabel()
        self._margin_label = QLabel()
        for label in (self._total_label, self._profit_label, self._margin_label):
            label.setObjectName("mutedLabel")
            summary_row.addWidget(label)
        summary_row.addStretch(1)
        layout.addLayout(summary_row)

        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Viewing:"))
        self._revision_selector = QComboBox()
        self._revision_selector.currentIndexChanged.connect(self._on_revision_changed)
        controls_row.addWidget(self._revision_selector)
        controls_row.addStretch(1)

        self._add_button = QPushButton("+ Add Line")
        self._add_button.clicked.connect(self._add_line)
        self._remove_button = QPushButton("Remove Line")
        self._remove_button.clicked.connect(self._remove_line)
        self._new_revision_button = QPushButton("Start New Revision")
        self._new_revision_button.clicked.connect(self._start_new_revision)
        self._mark_final_button = QPushButton("Mark as Final Estimate")
        self._mark_final_button.clicked.connect(self._mark_final)
        for button in (
            self._add_button,
            self._remove_button,
            self._new_revision_button,
            self._mark_final_button,
        ):
            controls_row.addWidget(button)
        layout.addLayout(controls_row)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self._table, 1)

    def refresh(self) -> None:
        def _load():
            with session_scope() as session:
                project = session.get(Project, self._project_id)
                current = get_or_create_current_revision(session, project)
                revisions = list_estimate_revisions(session, project)
                snapshot = build_project_financial_snapshot(session, project)
                return project, current, revisions, snapshot

        result = run_guarded(self, _load, context="loading estimated costs")
        if result is None:
            return
        project, current_revision, revisions, snapshot = result

        self._total_label.setText(f"Total Estimated Cost: {format_money(snapshot.estimated_cost, project.contract_currency)}")
        self._profit_label.setText(f"Estimated Profit: {format_money(snapshot.estimated_profit, project.contract_currency)}")
        self._margin_label.setText(f"Estimated Margin: {format_percentage(snapshot.estimated_margin)}")

        self._revision_selector.blockSignals(True)
        self._revision_selector.clear()
        self._revision_ids = [r.id for r in revisions]
        for revision in revisions:
            label_bits = [f"Revision {revision.revision_number}"]
            if revision.revision_number == revisions[0].revision_number:
                label_bits.append("(Original)")
            if revision.id == current_revision.id:
                label_bits.append("(Current)")
            if revision.is_final:
                label_bits.append("(Final)")
            self._revision_selector.addItem(" ".join(label_bits), revision.id)
        # Default to viewing the current/latest revision.
        current_index = self._revision_selector.findData(current_revision.id)
        self._revision_selector.setCurrentIndex(max(current_index, 0))
        self._revision_selector.blockSignals(False)

        self._current_revision_id = current_revision.id
        self._project_currency = project.contract_currency
        self._load_selected_revision()

    def _selected_revision_id(self) -> int | None:
        return self._revision_selector.currentData()

    def _is_viewing_current_revision(self) -> bool:
        return self._selected_revision_id() == getattr(self, "_current_revision_id", None)

    def _on_revision_changed(self) -> None:
        self._load_selected_revision()

    def _load_selected_revision(self) -> None:
        revision_id = self._selected_revision_id()
        if revision_id is None:
            self._table.setRowCount(0)
            return

        def _load():
            with session_scope() as session:
                from app.models import EstimateRevision

                revision = session.get(EstimateRevision, revision_id)
                return list_estimated_costs(session, revision)

        lines = run_guarded(self, _load, context="loading estimate revision lines")
        if lines is None:
            return

        editable = self._is_viewing_current_revision()
        self._add_button.setEnabled(editable)
        self._remove_button.setEnabled(editable)

        self._table.setRowCount(len(lines))
        for row, line in enumerate(lines):
            values = [
                line.cost_category.name if line.cost_category else "—",
                line.description or "",
                format_quantity(line.quantity),
                line.unit or "",
                format_money(line.unit_rate, line.currency) if line.unit_rate is not None else "—",
                format_money(line.amount, line.currency),
                line.notes or "",
            ]
            for col, text in enumerate(values):
                item = ValueSortItem(text, None)
                if col == 0:
                    item.setData(Qt.UserRole, line.id)
                self._table.setItem(row, col, item)

    def _add_line(self) -> None:
        from app.ui.costs.estimated_cost_dialog import EstimatedCostDialog

        def _open_dialog():
            with session_scope() as session:
                project = session.get(Project, self._project_id)
                revision = get_or_create_current_revision(session, project)
                return project, revision

        result = run_guarded(self, _open_dialog, context="preparing estimate line dialog")
        if result is None:
            return
        project, revision = result

        if EstimatedCostDialog(self, project=project, revision=revision).exec():
            self.refresh()

    def _remove_line(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        line_id = self._table.item(row, 0).data(Qt.UserRole)

        confirm = QMessageBox.question(
            self, "Remove line", "Remove this estimate line? This cannot be undone."
        )
        if confirm != QMessageBox.Yes:
            return

        def _remove():
            with session_scope() as session:
                from app.models import EstimatedCost

                project = session.get(Project, self._project_id)
                line = session.get(EstimatedCost, line_id)
                remove_estimated_cost_line(session, project, line)
            return True

        if run_guarded(self, _remove, context="removing estimate line"):
            self.refresh()

    def _start_new_revision(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Start new revision",
            "Start a new estimate revision? The current revision's lines will be copied "
            "forward as a starting point and the current one will become read-only history.",
        )
        if confirm != QMessageBox.Yes:
            return

        def _start():
            with session_scope() as session:
                project = session.get(Project, self._project_id)
                start_new_estimate_revision(session, project)
            return True

        if run_guarded(self, _start, context="starting new estimate revision"):
            self.refresh()

    def _mark_final(self) -> None:
        def _mark():
            with session_scope() as session:
                from app.models import EstimateRevision

                project = session.get(Project, self._project_id)
                revision = session.get(EstimateRevision, self._selected_revision_id())
                mark_revision_final(session, project, revision)
            return True

        if run_guarded(self, _mark, context="marking estimate revision final"):
            self.refresh()
