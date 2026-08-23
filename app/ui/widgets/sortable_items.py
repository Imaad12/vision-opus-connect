"""QTableWidgetItem subclasses that sort by their underlying value (a
Decimal, date, or None) rather than by displayed text — so "AED 950,000"
sorts correctly against "AED 1,000,000" instead of alphabetically."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from PySide6.QtWidgets import QTableWidgetItem


class ValueSortItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value: Decimal | date | int | None) -> None:
        super().__init__(text)
        self._sort_value = sort_value

    def __lt__(self, other: Any) -> bool:
        other_value = getattr(other, "_sort_value", None)
        if self._sort_value is None:
            return other_value is not None
        if other_value is None:
            return False
        return self._sort_value < other_value
