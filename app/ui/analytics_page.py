"""Analytics placeholder — multi-year/trade/category profitability analysis
is Phase 3+ (analytics/) scope, building on the same financial engine."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AnalyticsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        label = QLabel(
            "Multi-year and cross-project profitability analytics will be added in a later phase,\n"
            "built on the same financial engine used throughout this application."
        )
        label.setObjectName("mutedLabel")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

    def refresh(self) -> None:
        pass
