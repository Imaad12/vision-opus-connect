"""A small card for a single headline financial figure.

Purely presentational — it is handed an already-formatted string (or a
Decimal it formats via `app.ui.formatting`) and never computes anything.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from app.core.enums import Currency
from app.ui.formatting import format_money


class KpiCard(QFrame):
    def __init__(self, label: str, value_text: str = "—", *, tooltip: str | None = None) -> None:
        super().__init__()
        self.setObjectName("card")
        if tooltip:
            self.setToolTip(tooltip)

        self._value_label = QLabel(value_text)
        self._value_label.setObjectName("kpiValue")

        title_label = QLabel(label.upper())
        title_label.setObjectName("kpiLabel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        layout.addWidget(title_label)
        layout.addWidget(self._value_label)

    def set_value_text(self, text: str) -> None:
        self._value_label.setText(text)

    def set_money_value(self, amount: Decimal | None, currency: Currency = Currency.AED) -> None:
        self._value_label.setText(format_money(amount, currency))
