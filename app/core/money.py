"""Money handling.

Financial amounts are always `decimal.Decimal`, never `float`, and always
paired with an explicit currency. This module intentionally does not
perform currency conversion — comparing or summing amounts in different
currencies is a business decision that belongs in an explicit future
service, not something the money type should do silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import DEFAULT_CURRENCY, Currency

CENTS = Decimal("0.01")


def quantize(amount: Decimal) -> Decimal:
    """Round a Decimal amount to 2 decimal places using standard rounding."""
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


class CurrencyMismatchError(ValueError):
    """Raised when an operation is attempted across two different currencies."""


@dataclass(frozen=True, slots=True)
class Money:
    """A monetary amount in a specific currency."""

    amount: Decimal
    currency: Currency = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"Money.amount must be a Decimal, got {type(self.amount).__name__}")

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"Cannot combine {self.currency} with {other.currency} without an explicit conversion"
            )

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def is_zero(self) -> bool:
        return self.amount == Decimal("0")
