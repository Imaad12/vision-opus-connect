from decimal import Decimal

import pytest

from app.core.enums import Currency
from app.core.money import CurrencyMismatchError, Money, quantize


def test_quantize_rounds_to_cents() -> None:
    assert quantize(Decimal("10.005")) == Decimal("10.01")
    assert quantize(Decimal("10.004")) == Decimal("10.00")


def test_money_requires_decimal_amount() -> None:
    with pytest.raises(TypeError):
        Money(amount=10.5, currency=Currency.AED)  # type: ignore[arg-type]


def test_money_addition_same_currency() -> None:
    total = Money(Decimal("100"), Currency.AED) + Money(Decimal("50"), Currency.AED)
    assert total == Money(Decimal("150"), Currency.AED)


def test_money_subtraction_same_currency() -> None:
    result = Money(Decimal("100"), Currency.AED) - Money(Decimal("30"), Currency.AED)
    assert result == Money(Decimal("70"), Currency.AED)


def test_money_addition_different_currency_raises() -> None:
    with pytest.raises(CurrencyMismatchError):
        Money(Decimal("100"), Currency.AED) + Money(Decimal("50"), Currency.USD)


def test_money_is_zero() -> None:
    assert Money(Decimal("0"), Currency.AED).is_zero()
    assert not Money(Decimal("0.01"), Currency.AED).is_zero()


def test_default_currency_is_aed() -> None:
    assert Money(Decimal("10")).currency == Currency.AED
