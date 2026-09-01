"""Dashboard: portfolio-wide financial summary.

All figures come from `app.services.dashboard_service.build_dashboard_summary`,
which in turn only ever reads already-computed `ProjectFinancialSnapshot`
values — nothing here is calculated independently.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.enums import Currency
from app.database.session import session_scope
from app.services.dashboard_service import build_dashboard_summary
from app.ui.errors import run_guarded
from app.ui.formatting import format_money, format_percentage
from app.ui.widgets.kpi_card import KpiCard


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Portfolio-wide financial summary, computed from the financial engine.")
        subtitle.setObjectName("mutedLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        counts_row = QHBoxLayout()
        counts_row.setSpacing(12)
        self._total_card = KpiCard("Total Projects")
        self._active_card = KpiCard("Active Projects")
        self._completed_card = KpiCard("Completed Projects")
        for card in (self._total_card, self._active_card, self._completed_card):
            counts_row.addWidget(card)
        layout.addLayout(counts_row)

        revenue_heading = QLabel("Revenue, Cost & Profit — kept distinct, never combined into one number")
        revenue_heading.setObjectName("sectionTitle")
        layout.addWidget(revenue_heading)

        grid = QGridLayout()
        grid.setSpacing(12)
        self._awarded_card = KpiCard(
            "Total Awarded Contract Value", tooltip="Sum of Project.contract_value across awarded projects."
        )
        self._invoiced_card = KpiCard(
            "Total Invoiced Revenue", tooltip="Sum of client invoices raised, net of VAT."
        )
        self._actual_cost_card = KpiCard(
            "Total Actual Cost", tooltip="Sum of recognized actual cost across all projects."
        )
        self._actual_profit_card = KpiCard(
            "Total Actual Profit", tooltip="Actual revenue minus actual cost, summed across projects."
        )
        self._avg_actual_margin_card = KpiCard(
            "Average Actual Margin",
            tooltip="Mean of actual margin across projects that have actual revenue — "
            "projects without revenue yet are excluded, not counted as 0%.",
        )
        self._estimated_profit_card = KpiCard(
            "Total Estimated Profit", tooltip="Sum of estimated profit (awarded value minus estimated cost)."
        )
        self._avg_estimated_margin_card = KpiCard("Average Estimated Margin")

        cards = [
            self._awarded_card,
            self._invoiced_card,
            self._actual_cost_card,
            self._actual_profit_card,
            self._avg_actual_margin_card,
            self._estimated_profit_card,
            self._avg_estimated_margin_card,
        ]
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)
        layout.addStretch(1)

    def refresh(self) -> None:
        def _load():
            with session_scope() as session:
                return build_dashboard_summary(session)

        summary = run_guarded(self, _load, context="loading dashboard summary")
        if summary is None:
            return

        currency = Currency.AED
        self._total_card.set_value_text(str(summary.total_projects))
        self._active_card.set_value_text(str(summary.active_projects))
        self._completed_card.set_value_text(str(summary.completed_projects))

        self._awarded_card.set_money_value(summary.total_awarded_contract_value, currency)
        self._invoiced_card.set_money_value(summary.total_invoiced_revenue, currency)
        self._actual_cost_card.set_money_value(summary.total_actual_cost, currency)
        self._actual_profit_card.set_money_value(summary.total_actual_profit, currency)
        self._avg_actual_margin_card.set_value_text(format_percentage(summary.average_actual_margin))
        self._estimated_profit_card.set_money_value(summary.total_estimated_profit, currency)
        self._avg_estimated_margin_card.set_value_text(format_percentage(summary.average_estimated_margin))
