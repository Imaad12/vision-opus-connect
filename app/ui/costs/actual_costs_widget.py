"""Actual Costs tab content: entries, cost-by-category, and variance
against the latest estimate. Actual costs never modify or interact with
EstimatedCost rows at all."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.database.session import session_scope
from app.models import Project
from app.services.cost_service import cost_by_category, list_actual_costs, net_amount_of
from app.services.financial_service import build_project_financial_snapshot
from app.ui.errors import run_guarded
from app.ui.formatting import format_date, format_money, format_signed_money
from app.ui.variance_labels import describe_cost_variance
from app.ui.widgets.sortable_items import ValueSortItem
from app.ui.widgets.status_badge import Badge

COLUMNS = [
    "Date",
    "Category",
    "Description",
    "Supplier",
    "Reference",
    "Net Amount",
    "Tax Amount",
    "Gross Amount",
    "Payment Status",
]


class ActualCostsWidget(QWidget):
    def __init__(self, project_id: int) -> None:
        super().__init__()
        self._project_id = project_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        summary_row = QHBoxLayout()
        self._total_label = QLabel()
        self._total_label.setObjectName("mutedLabel")
        summary_row.addWidget(self._total_label)
        self._variance_label = QLabel()
        summary_row.addWidget(self._variance_label)
        self._variance_badge = Badge("")
        summary_row.addWidget(self._variance_badge)
        summary_row.addStretch(1)
        add_button = QPushButton("+ Add Actual Cost")
        add_button.clicked.connect(self._add_cost)
        summary_row.addWidget(add_button)
        layout.addLayout(summary_row)

        body_row = QHBoxLayout()
        body_row.setSpacing(16)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        body_row.addWidget(self._table, 3)

        category_panel = QVBoxLayout()
        category_heading = QLabel("Cost by Category")
        category_heading.setObjectName("sectionTitle")
        category_panel.addWidget(category_heading)
        self._category_list = QListWidget()
        category_panel.addWidget(self._category_list, 1)
        body_row.addLayout(category_panel, 1)

        layout.addLayout(body_row, 1)

    def refresh(self) -> None:
        def _load():
            with session_scope() as session:
                project = session.get(Project, self._project_id)
                costs = list_actual_costs(session, project)
                by_category = cost_by_category(session, project)
                snapshot = build_project_financial_snapshot(session, project)
                return project, costs, by_category, snapshot

        result = run_guarded(self, _load, context="loading actual costs")
        if result is None:
            return
        project, costs, by_category, snapshot = result
        currency = project.contract_currency

        self._total_label.setText(f"Total Actual Cost: {format_money(snapshot.actual_cost, currency)}")
        variance_text, sentiment = describe_cost_variance(snapshot.cost_variance)
        self._variance_label.setText(
            f"vs. Latest Estimate: {format_signed_money(snapshot.cost_variance, currency)}"
        )
        self._variance_badge.set_sentiment(variance_text, sentiment)

        self._table.setRowCount(len(costs))
        for row, cost in enumerate(costs):
            net = net_amount_of(cost)
            values = [
                (format_date(cost.incurred_date), cost.incurred_date),
                (cost.cost_category.name if cost.cost_category else "—", None),
                (cost.description or "", None),
                (cost.vendor.name if cost.vendor else "—", None),
                (cost.reference_number or "", None),
                (format_money(net, cost.currency), net),
                (format_money(cost.tax_amount, cost.currency) if cost.tax_amount is not None else "—", cost.tax_amount),
                (format_money(cost.amount, cost.currency), cost.amount),
                (cost.payment_status.value.replace("_", " ").title(), None),
            ]
            for col, (text, sort_value) in enumerate(values):
                item = ValueSortItem(text, sort_value)
                if col == 0:
                    item.setData(Qt.UserRole, cost.id)
                self._table.setItem(row, col, item)

        self._category_list.clear()
        for category, total in by_category:
            self._category_list.addItem(QListWidgetItem(f"{category.name}: {format_money(total, currency)}"))

    def _add_cost(self) -> None:
        from app.ui.costs.actual_cost_dialog import ActualCostDialog

        def _load_project():
            with session_scope() as session:
                return session.get(Project, self._project_id)

        project = run_guarded(self, _load_project, context="loading project")
        if project is None:
            return

        if ActualCostDialog(self, project=project).exec():
            self.refresh()
