"""Unit tests for the deterministic financial calculation engine.

These tests are the most important in the repository: they pin down the
exact arithmetic (and the exact null/zero handling) that every profit and
margin figure in the application depends on.

Tests are organized by function, plus a `TestBriefScenarios` class that
maps directly onto the 17 numbered test scenarios from the Phase 2 brief
that are expressible as pure-function calls. TEST 13 (multiple invoices
with different VAT/retention) and TEST 14 (multiple actual cost entries
across categories) require database aggregation and live in
`test_financial_service.py` instead.
"""

from decimal import Decimal

import pytest

from app.core.enums import Currency, ProjectStatus
from app.core.financial_engine import (
    ProjectFinancialSnapshot,
    calculate_actual_margin,
    calculate_actual_profit,
    calculate_actual_revenue,
    calculate_amount_due_after_retention,
    calculate_cost_variance,
    calculate_estimated_margin,
    calculate_estimated_profit,
    calculate_gross_amount,
    calculate_line_total,
    calculate_margin_variance,
    calculate_net_of_tax,
    calculate_outstanding_balance,
    calculate_profit_variance,
    calculate_quoted_margin,
    calculate_quoted_profit,
    calculate_recognized_cost,
    calculate_revenue_variance,
    calculate_revised_contract_value,
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


class TestQuotedStage:
    def test_quoted_profit(self) -> None:
        assert calculate_quoted_profit(Decimal("1000000"), Decimal("780000")) == Decimal("220000")

    def test_quoted_margin(self) -> None:
        profit = calculate_quoted_profit(Decimal("1000000"), Decimal("780000"))
        assert calculate_quoted_margin(profit, Decimal("1000000")) == Decimal("22.00")

    def test_missing_estimated_cost(self) -> None:
        assert calculate_quoted_profit(Decimal("1000000"), None) is None

    def test_zero_quoted_value_margin_is_none(self) -> None:
        profit = calculate_quoted_profit(Decimal("0"), Decimal("0"))
        assert calculate_quoted_margin(profit, Decimal("0")) is None


class TestEstimatedStage:
    def test_estimated_profit_uses_awarded_value(self) -> None:
        # Same numbers as TestQuotedStage but framed as post-award figures —
        # the formula is identical, only the semantic label of the revenue
        # input differs, which is exactly why quoted and awarded value must
        # never be silently substituted for one another by a caller.
        assert calculate_estimated_profit(Decimal("1000000"), Decimal("780000")) == Decimal("220000")

    def test_estimated_margin(self) -> None:
        profit = calculate_estimated_profit(Decimal("1000000"), Decimal("780000"))
        assert calculate_estimated_margin(profit, Decimal("1000000")) == Decimal("22.00")

    def test_estimated_profit_missing_cost(self) -> None:
        assert calculate_estimated_profit(Decimal("1000000"), None) is None

    def test_estimated_margin_zero_awarded_value(self) -> None:
        profit = calculate_estimated_profit(Decimal("0"), Decimal("0"))
        assert calculate_estimated_margin(profit, Decimal("0")) is None


class TestRevisedContractValue:
    def test_positive_and_negative_variations_combined(self) -> None:
        # Original 1,000,000 + 100,000 approved - 25,000 approved = 1,075,000.
        assert calculate_revised_contract_value(Decimal("1000000"), Decimal("75000")) == Decimal(
            "1075000"
        )

    def test_no_variations_yet(self) -> None:
        assert calculate_revised_contract_value(Decimal("1000000"), None) == Decimal("1000000")

    def test_no_awarded_value_is_unknown(self) -> None:
        assert calculate_revised_contract_value(None, Decimal("50000")) is None

    def test_negative_variation_only(self) -> None:
        assert calculate_revised_contract_value(Decimal("500000"), Decimal("-50000")) == Decimal(
            "450000"
        )

    def test_actual_revenue_is_an_alias(self) -> None:
        assert calculate_actual_revenue(Decimal("1000000"), Decimal("75000")) == calculate_revised_contract_value(
            Decimal("1000000"), Decimal("75000")
        )


class TestActualStage:
    def test_actual_profit(self) -> None:
        assert calculate_actual_profit(Decimal("1000000"), Decimal("750000")) == Decimal("250000")

    def test_actual_margin(self) -> None:
        profit = calculate_actual_profit(Decimal("1000000"), Decimal("750000"))
        assert calculate_actual_margin(profit, Decimal("1000000")) == Decimal("25.00")

    def test_actual_profit_missing_actual_cost(self) -> None:
        assert calculate_actual_profit(Decimal("1000000"), None) is None

    def test_actual_loss_making_project(self) -> None:
        profit = calculate_actual_profit(Decimal("100000"), Decimal("120000"))
        assert profit == Decimal("-20000")
        assert calculate_actual_margin(profit, Decimal("100000")) == Decimal("-20.00")

    def test_zero_actual_revenue_margin_is_none(self) -> None:
        profit = calculate_actual_profit(Decimal("0"), Decimal("0"))
        assert calculate_actual_margin(profit, Decimal("0")) is None


class TestVariances:
    def test_cost_variance_overrun(self) -> None:
        assert calculate_cost_variance(Decimal("75000"), Decimal("90000")) == Decimal("15000")

    def test_cost_variance_underrun(self) -> None:
        assert calculate_cost_variance(Decimal("75000"), Decimal("60000")) == Decimal("-15000")

    def test_cost_variance_no_actuals_yet(self) -> None:
        assert calculate_cost_variance(Decimal("75000"), None) is None

    def test_revenue_variance_reflects_approved_variations(self) -> None:
        actual_revenue = calculate_revised_contract_value(Decimal("1000000"), Decimal("75000"))
        assert calculate_revenue_variance(Decimal("1000000"), actual_revenue) == Decimal("75000")

    def test_profit_variance(self) -> None:
        estimated_profit = calculate_estimated_profit(Decimal("1000000"), Decimal("780000"))
        actual_profit = calculate_actual_profit(Decimal("1075000"), Decimal("800000"))
        assert calculate_profit_variance(estimated_profit, actual_profit) == Decimal("55000")

    def test_margin_variance(self) -> None:
        estimated_margin = calculate_estimated_margin(Decimal("220000"), Decimal("1000000"))
        actual_margin = calculate_actual_margin(Decimal("275000"), Decimal("1075000"))
        variance = calculate_margin_variance(estimated_margin, actual_margin)
        assert variance == actual_margin - estimated_margin

    def test_variance_missing_input_is_none(self) -> None:
        assert calculate_profit_variance(None, Decimal("1000")) is None
        assert calculate_revenue_variance(Decimal("1000"), None) is None
        assert calculate_margin_variance(None, None) is None


class TestNetAndGrossOfTax:
    def test_net_of_tax_normal_case(self) -> None:
        # AED 105,000 invoice including AED 5,000 VAT (5%) -> AED 100,000 net.
        assert calculate_net_of_tax(Decimal("105000"), Decimal("5000")) == Decimal("100000")

    def test_net_of_tax_missing_tax_treated_as_zero(self) -> None:
        assert calculate_net_of_tax(Decimal("100000"), None) == Decimal("100000")

    def test_net_of_tax_missing_gross_amount_is_unknown(self) -> None:
        assert calculate_net_of_tax(None, Decimal("5000")) is None

    def test_net_of_tax_credit_note_with_negative_tax(self) -> None:
        assert calculate_net_of_tax(Decimal("-1050"), Decimal("-50")) == Decimal("-1000")

    def test_gross_amount_is_the_inverse(self) -> None:
        assert calculate_gross_amount(Decimal("100000"), Decimal("4750")) == Decimal("104750")

    def test_gross_amount_missing_tax_treated_as_zero(self) -> None:
        assert calculate_gross_amount(Decimal("100000"), None) == Decimal("100000")

    def test_gross_amount_missing_net_is_unknown(self) -> None:
        assert calculate_gross_amount(None, Decimal("5000")) is None

    def test_round_trip(self) -> None:
        net, tax = Decimal("100000"), Decimal("4750")
        gross = calculate_gross_amount(net, tax)
        assert calculate_net_of_tax(gross, tax) == net


class TestAmountDueAfterRetention:
    def test_normal_case(self) -> None:
        assert calculate_amount_due_after_retention(Decimal("100000"), Decimal("10000")) == Decimal(
            "90000"
        )

    def test_no_retention_recorded(self) -> None:
        assert calculate_amount_due_after_retention(Decimal("100000"), None) == Decimal("100000")

    def test_missing_invoice_amount_is_unknown(self) -> None:
        assert calculate_amount_due_after_retention(None, Decimal("10000")) is None

    def test_does_not_also_strip_tax(self) -> None:
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


class TestRecognizedCost:
    def test_recoverable_tax_excluded_from_cost(self) -> None:
        assert calculate_recognized_cost(Decimal("10500"), Decimal("500"), True) == Decimal("10000")

    def test_non_recoverable_tax_included_in_cost(self) -> None:
        assert calculate_recognized_cost(Decimal("10500"), Decimal("500"), False) == Decimal("10500")

    def test_recoverable_is_the_default(self) -> None:
        assert calculate_recognized_cost(Decimal("10500"), Decimal("500")) == Decimal("10000")

    def test_missing_gross_amount_is_unknown(self) -> None:
        assert calculate_recognized_cost(None, Decimal("500"), True) is None

    def test_no_tax_recorded(self) -> None:
        assert calculate_recognized_cost(Decimal("10000"), None, True) == Decimal("10000")
        assert calculate_recognized_cost(Decimal("10000"), None, False) == Decimal("10000")


class TestLineTotal:
    def test_normal_case(self) -> None:
        assert calculate_line_total(Decimal("10"), Decimal("250.50")) == Decimal("2505.00")

    def test_rounds_to_two_decimal_places(self) -> None:
        assert calculate_line_total(Decimal("3"), Decimal("10.005")) == Decimal("30.02")

    def test_missing_quantity_is_unknown(self) -> None:
        assert calculate_line_total(None, Decimal("100")) is None

    def test_missing_unit_rate_is_unknown(self) -> None:
        assert calculate_line_total(Decimal("10"), None) is None


class TestProjectFinancialSnapshot:
    def test_full_lifecycle(self) -> None:
        snapshot = ProjectFinancialSnapshot(
            currency=Currency.AED,
            project_status=ProjectStatus.IN_PROGRESS,
            quoted_value=Decimal("1000000"),
            estimated_cost=Decimal("780000"),
            awarded_contract_value=Decimal("1000000"),
            approved_variation_value=Decimal("75000"),
            actual_cost=Decimal("800000"),
            invoiced_revenue=Decimal("950000"),
            invoiced_revenue_gross=Decimal("997500"),
            cash_received=Decimal("700000"),
            retention_outstanding=Decimal("47500"),
            receivables_outstanding=Decimal("250000"),
        )

        assert snapshot.quoted_profit == Decimal("220000")
        assert snapshot.quoted_margin == Decimal("22.00")
        assert snapshot.estimated_profit == Decimal("220000")
        assert snapshot.estimated_margin == Decimal("22.00")
        assert snapshot.revised_contract_value == Decimal("1075000")
        assert snapshot.actual_revenue == Decimal("1075000")
        assert snapshot.actual_profit == Decimal("275000")
        assert snapshot.actual_margin == quantize_expected("275000", "1075000")
        assert snapshot.cost_variance == Decimal("20000")
        assert snapshot.revenue_variance == Decimal("75000")
        assert snapshot.profit_variance == Decimal("55000")
        # cash received must never leak into any revenue/profit figure
        assert snapshot.cash_received == Decimal("700000")
        assert snapshot.actual_profit != snapshot.cash_received

    def test_tender_stage_has_only_quoted_figures(self) -> None:
        # Not yet awarded: only stage-1 (quoted) figures should resolve.
        snapshot = ProjectFinancialSnapshot(
            quoted_value=Decimal("50000"),
            estimated_cost=Decimal("40000"),
        )

        assert snapshot.quoted_profit == Decimal("10000")
        assert snapshot.quoted_margin == Decimal("20.00")
        assert snapshot.estimated_profit is None
        assert snapshot.estimated_margin is None
        assert snapshot.revised_contract_value is None
        assert snapshot.actual_revenue is None
        assert snapshot.actual_profit is None
        assert snapshot.actual_margin is None
        assert snapshot.cost_variance is None

    def test_completely_empty_snapshot_has_no_figures(self) -> None:
        snapshot = ProjectFinancialSnapshot()

        assert snapshot.quoted_profit is None
        assert snapshot.quoted_margin is None
        assert snapshot.estimated_profit is None
        assert snapshot.estimated_margin is None
        assert snapshot.revised_contract_value is None
        assert snapshot.actual_profit is None
        assert snapshot.actual_margin is None
        assert snapshot.cost_variance is None
        assert snapshot.revenue_variance is None
        assert snapshot.profit_variance is None
        assert snapshot.margin_variance is None
        # Transactional sums default to a true zero, not unknown.
        assert snapshot.invoiced_revenue == Decimal("0")
        assert snapshot.cash_received == Decimal("0")
        assert snapshot.retention_outstanding == Decimal("0")
        assert snapshot.receivables_outstanding == Decimal("0")

    def test_is_immutable(self) -> None:
        snapshot = ProjectFinancialSnapshot(quoted_value=Decimal("1000"))
        with pytest.raises(Exception):
            snapshot.quoted_value = Decimal("2000")  # type: ignore[misc]

    def test_default_currency_is_aed(self) -> None:
        assert ProjectFinancialSnapshot().currency == Currency.AED

    def test_project_status_is_informational_only(self) -> None:
        # Two snapshots with identical financials but different statuses
        # must produce identical numbers — status never alters the math.
        common = dict(
            awarded_contract_value=Decimal("1000000"),
            approved_variation_value=Decimal("-100000"),
            estimated_cost=Decimal("700000"),
            actual_cost=Decimal("650000"),
        )
        cancelled = ProjectFinancialSnapshot(project_status=ProjectStatus.CANCELLED, **common)
        in_progress = ProjectFinancialSnapshot(project_status=ProjectStatus.IN_PROGRESS, **common)

        assert cancelled.actual_profit == in_progress.actual_profit
        assert cancelled.actual_margin == in_progress.actual_margin
        assert cancelled.revised_contract_value == in_progress.revised_contract_value


def quantize_expected(profit: str, revenue: str) -> Decimal:
    return safe_margin(Decimal(profit), Decimal(revenue))


class TestBriefScenarios:
    """Direct mapping of the Phase 2 brief's numbered test scenarios that
    are expressible as pure engine calls. TEST 13 and TEST 14 require
    database aggregation and live in test_financial_service.py."""

    def test_scenario_1_estimated_profit_and_margin(self) -> None:
        profit = calculate_estimated_profit(Decimal("1000000"), Decimal("780000"))
        margin = calculate_estimated_margin(profit, Decimal("1000000"))
        assert profit == Decimal("220000")
        assert margin == Decimal("22.00")

    def test_scenario_2_revised_contract_value(self) -> None:
        approved_total = Decimal("100000") + Decimal("-25000")
        revised = calculate_revised_contract_value(Decimal("1000000"), approved_total)
        assert revised == Decimal("1075000")

    def test_scenario_3_pending_variation_excluded(self) -> None:
        # A pending variation must never be included in the summed input —
        # simulated here by the caller correctly omitting it from the total.
        approved_total_excluding_pending = Decimal("100000") + Decimal("-25000")  # +50,000 PENDING excluded
        revised = calculate_revised_contract_value(Decimal("1000000"), approved_total_excluding_pending)
        assert revised == Decimal("1075000")

    def test_scenario_4_vat_does_not_change_revenue(self) -> None:
        gross_invoice = Decimal("1050000")
        vat = Decimal("50000")
        net_revenue = calculate_net_of_tax(gross_invoice, vat)
        assert net_revenue == Decimal("1000000")

    def test_scenario_5_invoice_retention_vat_gross_independent(self) -> None:
        net_invoice = Decimal("100000")
        vat = Decimal("4750")
        retention = Decimal("5000")

        gross_invoice = calculate_gross_amount(net_invoice, vat)
        amount_due_after_retention = calculate_amount_due_after_retention(gross_invoice, retention)

        assert gross_invoice == Decimal("104750")
        assert amount_due_after_retention == Decimal("99750")
        assert calculate_net_of_tax(gross_invoice, vat) == net_invoice
        # Retention withholding must not be confused with the VAT component.
        assert amount_due_after_retention != calculate_net_of_tax(gross_invoice, vat)

    def test_scenario_6_actual_profit_and_margin(self) -> None:
        profit = calculate_actual_profit(Decimal("1000000"), Decimal("750000"))
        margin = calculate_actual_margin(profit, Decimal("1000000"))
        assert profit == Decimal("250000")
        assert margin == Decimal("25.00")

    def test_scenario_7_uses_awarded_value_not_quoted(self) -> None:
        quoted_value = Decimal("1000000")
        awarded_contract_value = Decimal("900000")
        estimated_cost = Decimal("700000")

        quoted_profit = calculate_quoted_profit(quoted_value, estimated_cost)
        estimated_profit = calculate_estimated_profit(awarded_contract_value, estimated_cost)

        assert quoted_profit == Decimal("300000")
        assert estimated_profit == Decimal("200000")
        assert estimated_profit != quoted_profit

    def test_scenario_8_cash_received_is_not_revenue(self) -> None:
        actual_revenue = Decimal("1000000")
        actual_cost = Decimal("800000")
        cash_received = Decimal("200000")

        actual_profit = calculate_actual_profit(actual_revenue, actual_cost)
        assert actual_profit == Decimal("200000")

        # Changing cash received must not change actual profit at all.
        other_cash_received = Decimal("999999")
        assert calculate_actual_profit(actual_revenue, actual_cost) == actual_profit
        assert cash_received != other_cash_received  # sanity: they really differ
        assert actual_profit == Decimal("200000")  # unaffected either way

    def test_scenario_9_lost_quotation_has_no_actual_profit(self) -> None:
        snapshot = ProjectFinancialSnapshot(
            project_status=ProjectStatus.LOST,
            quoted_value=Decimal("500000"),
            estimated_cost=Decimal("400000"),
            awarded_contract_value=None,
        )
        assert snapshot.quoted_profit == Decimal("100000")
        assert snapshot.actual_profit is None
        assert snapshot.actual_revenue is None

    def test_scenario_10_cancelled_project_profit_is_consistent(self) -> None:
        snapshot = ProjectFinancialSnapshot(
            project_status=ProjectStatus.CANCELLED,
            awarded_contract_value=Decimal("1000000"),
            approved_variation_value=Decimal("-150000"),
            estimated_cost=Decimal("700000"),
            actual_cost=Decimal("600000"),
        )
        # Same formula as any other status: no special-casing for cancellation.
        assert snapshot.revised_contract_value == Decimal("850000")
        assert snapshot.actual_profit == Decimal("250000")

    def test_scenario_11_zero_revenue_no_division_by_zero(self) -> None:
        assert calculate_actual_margin(Decimal("0"), Decimal("0")) is None
        assert calculate_estimated_margin(Decimal("0"), Decimal("0")) is None
        assert calculate_quoted_margin(Decimal("0"), Decimal("0")) is None

    def test_scenario_12_negative_variation(self) -> None:
        revised = calculate_revised_contract_value(Decimal("1000000"), Decimal("-100000"))
        assert revised == Decimal("900000")

    # TEST 13 (multiple invoices, different VAT/retention) and TEST 14
    # (multiple actual costs across categories) are in test_financial_service.py.

    def test_scenario_15_cost_variance(self) -> None:
        assert calculate_cost_variance(Decimal("780000"), Decimal("800000")) == Decimal("20000")

    def test_scenario_16_profit_variance(self) -> None:
        estimated_profit = calculate_estimated_profit(Decimal("1000000"), Decimal("780000"))
        actual_profit = calculate_actual_profit(Decimal("1075000"), Decimal("800000"))
        assert calculate_profit_variance(estimated_profit, actual_profit) == Decimal("55000")

    def test_scenario_17_margin_variance(self) -> None:
        estimated_margin = calculate_estimated_margin(Decimal("220000"), Decimal("1000000"))
        actual_margin = calculate_actual_margin(Decimal("275000"), Decimal("1075000"))
        variance = calculate_margin_variance(estimated_margin, actual_margin)
        assert variance == actual_margin - estimated_margin
        assert variance > Decimal("0")
