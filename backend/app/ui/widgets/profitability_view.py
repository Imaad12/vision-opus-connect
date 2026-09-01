"""Renders a `ProjectFinancialSnapshot`. Used by both the project Overview
tab and the dedicated Profitability tab — one widget, so the two screens
can never drift into showing different numbers for the same project.

This widget only formats and lays out values already computed by
`app.core.financial_engine` / `app.services.financial_service`. It
performs no arithmetic of its own beyond choosing which already-computed
property to display.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.financial_engine import ProjectFinancialSnapshot
from app.ui.formatting import format_money, format_percentage, format_signed_money
from app.ui.variance_labels import (
    describe_cost_variance,
    describe_margin_variance,
    describe_profit_variance,
    describe_revenue_variance,
)
from app.ui.widgets.status_badge import sentiment_badge


def _row(grid: QGridLayout, row: int, label: str, value: str, *, badge: QWidget | None = None) -> None:
    label_widget = QLabel(label)
    label_widget.setObjectName("mutedLabel")
    value_widget = QLabel(value)
    value_widget.setStyleSheet("font-weight: 600; font-size: 13px;")

    grid.addWidget(label_widget, row, 0)
    grid.addWidget(value_widget, row, 1)
    if badge is not None:
        grid.addWidget(badge, row, 2)


def _section(title: str) -> tuple[QFrame, QGridLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(16, 14, 16, 14)
    outer.setSpacing(10)

    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    outer.addWidget(heading)

    grid = QGridLayout()
    grid.setHorizontalSpacing(18)
    grid.setVerticalSpacing(8)
    grid.setColumnStretch(1, 1)
    outer.addLayout(grid)
    return frame, grid


class ProfitabilityView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        self._placeholder = QLabel("No financial data available yet.")
        self._placeholder.setObjectName("mutedLabel")
        self._layout.addWidget(self._placeholder)

    def set_snapshot(self, snapshot: ProjectFinancialSnapshot) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        currency = snapshot.currency

        contract_frame, contract_grid = _section("Contract")
        _row(contract_grid, 0, "Quoted Value", format_money(snapshot.quoted_value, currency))
        _row(contract_grid, 1, "Awarded Contract Value", format_money(snapshot.awarded_contract_value, currency))
        _row(contract_grid, 2, "Approved Variations", format_signed_money(snapshot.approved_variation_value, currency))
        _row(contract_grid, 3, "Revised Contract Value", format_money(snapshot.revised_contract_value, currency))
        revenue_text, revenue_sentiment = describe_revenue_variance(snapshot.revenue_variance)
        _row(
            contract_grid,
            4,
            "Revenue Variance",
            format_signed_money(snapshot.revenue_variance, currency),
            badge=sentiment_badge(revenue_text, revenue_sentiment),
        )

        estimated_frame, estimated_grid = _section("Estimated (using awarded contract value)")
        _row(estimated_grid, 0, "Estimated Cost", format_money(snapshot.estimated_cost, currency))
        _row(estimated_grid, 1, "Estimated Profit", format_money(snapshot.estimated_profit, currency))
        _row(estimated_grid, 2, "Estimated Margin", format_percentage(snapshot.estimated_margin))
        _row(estimated_grid, 3, "Quoted Profit (pre-award)", format_money(snapshot.quoted_profit, currency))
        _row(estimated_grid, 4, "Quoted Margin (pre-award)", format_percentage(snapshot.quoted_margin))

        actual_frame, actual_grid = _section("Actual")
        _row(actual_grid, 0, "Actual Revenue", format_money(snapshot.actual_revenue, currency))
        _row(actual_grid, 1, "Actual Cost", format_money(snapshot.actual_cost, currency))
        _row(actual_grid, 2, "Actual Profit", format_money(snapshot.actual_profit, currency))
        _row(actual_grid, 3, "Actual Margin", format_percentage(snapshot.actual_margin))

        variance_frame, variance_grid = _section("Estimated vs. Actual")
        cost_text, cost_sentiment = describe_cost_variance(snapshot.cost_variance)
        _row(
            variance_grid,
            0,
            "Cost Variance",
            format_signed_money(snapshot.cost_variance, currency),
            badge=sentiment_badge(cost_text, cost_sentiment),
        )
        profit_text, profit_sentiment = describe_profit_variance(snapshot.profit_variance)
        _row(
            variance_grid,
            1,
            "Profit Variance",
            format_signed_money(snapshot.profit_variance, currency),
            badge=sentiment_badge(profit_text, profit_sentiment),
        )
        margin_text, margin_sentiment = describe_margin_variance(snapshot.margin_variance)
        margin_variance_text = (
            "—" if snapshot.margin_variance is None else f"{snapshot.margin_variance:+.2f} pts"
        )
        _row(
            variance_grid,
            2,
            "Margin Variance",
            margin_variance_text,
            badge=sentiment_badge(margin_text, margin_sentiment),
        )

        cash_frame, cash_grid = _section("Invoicing & Cash Collection")
        _row(cash_grid, 0, "Invoiced Revenue (net of VAT)", format_money(snapshot.invoiced_revenue, currency))
        _row(cash_grid, 1, "Retention Outstanding", format_money(snapshot.retention_outstanding, currency))
        _row(cash_grid, 2, "Cash Received", format_money(snapshot.cash_received, currency))
        _row(cash_grid, 3, "Receivables Outstanding", format_money(snapshot.receivables_outstanding, currency))

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        top_row.addWidget(contract_frame)
        top_row.addWidget(estimated_frame)
        top_row.addWidget(actual_frame)
        self._layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        bottom_row.addWidget(variance_frame)
        bottom_row.addWidget(cash_frame)
        self._layout.addLayout(bottom_row)
