"""A currency-aware numeric input that always yields a `Decimal`, never a
`float` — Qt's QDoubleSpinBox is backed by a C double, which is exactly the
binary floating-point representation this project's money handling
(`app/core/money.py`) forbids. This widget is a validated QLineEdit
instead, parsed straight to Decimal.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit

# Optional leading minus, digits, optional 2 decimal places — matches the
# Numeric(14, 2) precision used throughout the schema.
_PATTERN = QRegularExpression(r"^-?\d{0,14}(\.\d{0,2})?$")


class MoneyLineEdit(QLineEdit):
    def __init__(self, *, allow_negative: bool = False, placeholder: str = "0.00") -> None:
        super().__init__()
        self.setPlaceholderText(placeholder)
        pattern = _PATTERN if allow_negative else QRegularExpression(r"^\d{0,14}(\.\d{0,2})?$")
        self.setValidator(QRegularExpressionValidator(pattern, self))

    def decimal_value(self) -> Decimal | None:
        text = self.text().strip()
        if not text or text == "-":
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    def set_decimal_value(self, value: Decimal | None) -> None:
        self.setText("" if value is None else f"{value:.2f}")
