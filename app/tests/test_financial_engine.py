"""Unit tests for the deterministic financial calculation engine.

These tests are the most important in the repository: they pin down the
exact arithmetic (and the exact null/zero handling) that every profit and
margin figure in the application depends on.
"""

from decimal import Decimal

import pytest

from app.core.enums import Currency
from app.core.financial_engine import (
    ProjectFinancials,
    calculate_actual_margin,
    calculate_actual_profit,
    calculate_actual_revenue,
    calculate_amount_due_after_retention,
    calculate_cost_variance,
    calculate_estimated_margin,
    calculate_estimated_profit,
    calculate_net_of_tax,
    calculate_outstanding_balance,
    safe_margin,
    safe_subtract,
)


class TestSafeSubtract:
    def test_normal_subtraction(self) -> None:
        assert safe_subtract(Decimal("100"), Decimal("40")) == Decimal("60")

    def test_none_minuend_returns_none(self) -> None:
        assert safe_subtract(None, Decimal("40")) is None

    def test_none_subtrahend_returns_none(self) -> None:
        assert safe_subtract(Decimal("100"), None) is None

    def test_both_none_returns_none(self) -> None:
        assert safe_subtract(None, None) is None

    def test_negative_result_allowed(self) -> None:
        # A loss-making project must show a negative profit, not be clamped to 0.
        assert safe_subtract(Decimal("50"), Decimal("80")) == Decimal("-30")


class TestSafeMargin:
    def test_normal_margin(self) -> None:
        assert safe_margin(Decimal("25"), Decimal("100")) == Decimal("25.00")

    def test_none_profit_returns_none(self) -> None:
        assert safe_margin(None, Decimal("100")) is None

    def test_none_revenue_returns_none(self) -> None:
        assert safe_margin(Decimal("25"), None) is None

    def test_zero_revenue_returns_none_not_zero_not_error(self) -> None:
        # Division by zero must never raise, and must not silently show 0%.
        assert safe_margin(Decimal("25"), Decimal("0")) is None

    def test_zero_profit_with_nonzero_revenue_is_zero_percent(self) -> None:
        assert safe_margin(Decimal("0"), Decimal("100")) == Decimal("0.00")

    def test_negative_margin(self) -> None:
        assert safe_margin(Decimal("-20"), Decimal("100")) == Decimal("-20.00")


class TestEstimatedProfitAndMargin:
    def test_estimated_profit(self) -> None:
        assert calculate_estimated_profit(Decimal("100000"), Decimal("75000")) == Decimal("25000")

    def test_estimated_profit_missing_cost(self) -> None:
        assert calculate_estimated_profit(Decimal("100000"), None) is None

    def test_estimated_margin(self) -> None:
        profit = calculate_estimated_profit(Decimal("100000"), Decimal("75000"))
        assert calculate_estimated_margin(profit, Decimal("100000")) == Decimal("25.00")

    def test_estimated_margin_zero_quoted_value(self) -> None:
        profit = calculate_estimated_profit(Decimal("0"), Decimal("0"))
        assert calculate_estimated_margin(profit, Decimal("0")) is None


class TestActualRevenue:
    def test_contract_value_only(self) -> None:
        assert calculate_actual_revenue(Decimal("100000"), None) == Decimal("100000")

    def test_contract_value_plus_variations(self) -> None:
        assert calculate_actual_revenue(Decimal("100000"), Decimal("5000")) == Decimal("105000")

    def test_no_contract_value_yet_is_unknown(self) -> None:
        # A project with no awarded contract has no actual revenue yet,
        # regardless of variations recorded (there should be none, but even
        # so this must not be treated as 0).
        assert calculate_actual_revenue(None, Decimal("5000")) is None

    def test_negative_variation_reduces_revenue(self) -> None:
        assert calculate_actual_revenue(Decimal("100000"), Decimal("-2000")) == Decimal("98000")


class TestActualProfitAndMargin:
    def test_actual_profit(self) -> None:
        assert calculate_actual_profit(Decimal("105000"), Decimal("90000")) == Decimal("15000")

    def test_actual_profit_missing_actual_cost(self) -> None:
        assert calculate_actual_profit(Decimal("105000"), None) is None

    def test_actual_margin(self) -> None:
        profit = calculate_actual_profit(Decimal("105000"), Decimal("90000"))
        assert calculate_actual_margin(profit, Decimal("105000")) == Decimal("14.29")

    def test_actual_loss_making_project(self) -> None:
        profit = calculate_actual_profit(Decimal("100000"), Decimal("120000"))
        assert profit == Decimal("-20000")
        assert calculate_actual_margin(profit, Decimal("100000")) == Decimal("-20.00")


class TestCostVariance:
    def test_over_budget(self) -> None:
        assert calculate_cost_variance(Decimal("75000"), Decimal("90000")) == Decimal("15000")

    def test_under_budget(self) -> None:
        assert calculate_cost_variance(Decimal("75000"), Decimal("60000")) == Decimal("-15000")

    def test_no_actuals_yet(self) -> None:
        assert calculate_cost_variance(Decimal("75000"), None) is None


class TestNetOfTax:
    def test_normal_case(self) -> None:
        # AED 105,000 invoice including AED 5,000 VAT (5%) -> AED 100,000 net.
        assert calculate_net_of_tax(Decimal("105000"), Decimal("5000")) == Decimal("100000")

    def test_missing_tax_treated_as_zero(self) -> None:
        # No VAT recorded is a known fact (no tax), not "unknown".
        assert calculate_net_of_tax(Decimal("100000"), None) == Decimal("100000")

    def test_missing_gross_amount_is_unknown(self) -> None:
        assert calculate_net_of_tax(None, Decimal("5000")) is None

    def test_credit_note_with_negative_tax(self) -> None:
        # A credit note reversing a prior invoice: both amount and tax are negative.
        assert calculate_net_of_tax(Decimal("-1050"), Decimal("-50")) == Decimal("-1000")


class TestAmountDueAfterRetention:
    def test_normal_case(self) -> None:
        # AED 100,000 invoice with 10% retention withheld.
        assert calculate_amount_due_after_retention(Decimal("100000"), Decimal("10000")) == Decimal(
            "90000"
        )

    def test_no_retention_recorded(self) -> None:
        assert calculate_amount_due_after_retention(Decimal("100000"), None) == Decimal("100000")

    def test_missing_invoice_amount_is_unknown(self) -> None:
        assert calculate_amount_due_after_retention(None, Decimal("10000")) is None

    def test_does_not_also_strip_tax(self) -> None:
        # Retention is withheld from the face value, independent of tax.
        result = calculate_amount_due_after_retention(Decimal("105000"), Decimal("10000"))
        assert result == Decimal("95000")


class TestOutstandingBalance:
    def test_partial_payment_leaves_a_balance(self) -> None:
        assert calculate_outstanding_balance(Decimal("100000"), Decimal("40000")) == Decimal("60000")

    def test_no_payments_yet(self) -> None:
        assert calculate_outstanding_balance(Decimal("100000"), None) == Decimal("100000")

    def test_fully_paid(self) -> None:
        assert calculate_outstanding_balance(Decimal("100000"), Decimal("100000")) == Decimal("0")

    def test_missing_amount_due_is_unknown(self) -> None:
        assert calculate_outstanding_balance(None, Decimal("1000")) is None

    def test_overpayment_is_negative(self) -> None:
        assert calculate_outstanding_balance(Decimal("100000"), Decimal("110000")) == Decimal("-10000")


class TestProjectFinancials:
    def test_full_lifecycle(self) -> None:
        financials = ProjectFinancials(
            currency=Currency.AED,
            quoted_value=Decimal("100000"),
            estimated_cost=Decimal("75000"),
            contract_value=Decimal("100000"),
            actual_cost=Decimal("80000"),
            approved_variation_total=Decimal("5000"),
        )

        assert financials.estimated_profit == Decimal("25000")
        assert financials.estimated_margin == Decimal("25.00")
        assert financials.actual_revenue == Decimal("105000")
        assert financials.actual_profit == Decimal("25000")
        assert financials.actual_margin == Decimal("23.81")
        assert financials.cost_variance == Decimal("5000")

    def test_tender_stage_only_has_no_actuals(self) -> None:
        # A project still at tender stage: quoted and estimated figures
        # exist, but nothing awarded or spent yet.
        financials = ProjectFinancials(
            quoted_value=Decimal("50000"),
            estimated_cost=Decimal("40000"),
        )

        assert financials.estimated_profit == Decimal("10000")
        assert financials.estimated_margin == Decimal("20.00")
        assert financials.actual_revenue is None
        assert financials.actual_profit is None
        assert financials.actual_margin is None
        assert financials.cost_variance is None

    def test_completely_empty_project_has_no_figures(self) -> None:
        financials = ProjectFinancials()

        assert financials.estimated_profit is None
        assert financials.estimated_margin is None
        assert financials.actual_revenue is None
        assert financials.actual_profit is None
        assert financials.actual_margin is None
        assert financials.cost_variance is None

    def test_is_immutable(self) -> None:
        financials = ProjectFinancials(quoted_value=Decimal("1000"))
        with pytest.raises(Exception):
            financials.quoted_value = Decimal("2000")  # type: ignore[misc]

    def test_default_currency_is_aed(self) -> None:
        assert ProjectFinancials().currency == Currency.AED
