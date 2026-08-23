"""Presentation-only formatting for numbers, dates, and currency.

Nothing here computes a financial figure — it only formats numbers that
`app.core.financial_engine` and the services layer already produced, for
display in Qt widgets. See app/core/financial_engine.py for the actual
math and app/core/money.py for rounding rules.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.enums import Currency

PLACEHOLDER = "—"


def format_money(amount: Decimal | None, currency: Currency | str | None = Currency.AED) -> str:
    """"AED 1,234,567.89", or a placeholder when the amount is unknown
    (None) rather than showing a misleading 0."""
    if amount is None:
        return PLACEHOLDER
    currency_code = currency.value if isinstance(currency, Currency) else (currency or "")
    sign = "-" if amount < 0 else ""
    return f"{sign}{currency_code} {abs(amount):,.2f}".strip()


def format_percentage(value: Decimal | None) -> str:
    """"22.00%", or a placeholder when the margin is undefined (None)."""
    if value is None:
        return PLACEHOLDER
    return f"{value:,.2f}%"


def format_signed_money(amount: Decimal | None, currency: Currency | str | None = Currency.AED) -> str:
    """Like `format_money`, but always shows an explicit +/- sign — for
    variance figures where the sign itself is the point."""
    if amount is None:
        return PLACEHOLDER
    currency_code = currency.value if isinstance(currency, Currency) else (currency or "")
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{currency_code} {abs(amount):,.2f}".strip()


def format_date(value: date | None) -> str:
    if value is None:
        return PLACEHOLDER
    return value.strftime("%d %b %Y")


def format_quantity(value: Decimal | None) -> str:
    if value is None:
        return PLACEHOLDER
    normalized = value.normalize()
    return f"{normalized:f}"
