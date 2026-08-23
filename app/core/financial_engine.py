"""Deterministic financial calculations.

Every function here is a pure function over `Decimal` inputs. There is no
database access, no I/O, and no AI in this module — profit and margin
figures must be reproducible and auditable, so they are computed the same
way every time from the same inputs.

Do not add any code path here (or anywhere else) that lets a language
model output feed into these calculations as a number. AI may later read
the *results* of this module to generate commentary, but it never computes
or overrides them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict

from app.core.enums import DEFAULT_CURRENCY, Currency
from app.core.money import quantize

ZERO: Final[Decimal] = Decimal("0")
HUNDRED: Final[Decimal] = Decimal("100")


def safe_subtract(minuend: Decimal | None, subtrahend: Decimal | None) -> Decimal | None:
    """Subtract two optional amounts, treating a missing operand as unknown.

    Returns None (not 0) if either input is None, so "we don't know the
    cost yet" is never displayed as "profit equals revenue".
    """
    if minuend is None or subtrahend is None:
        return None
    return minuend - subtrahend


def safe_margin(profit: Decimal | None, revenue: Decimal | None) -> Decimal | None:
    """Compute a percentage margin, guarding against None and zero revenue.

    Returns None when the margin is undefined (no revenue recorded, or
    profit/revenue unknown) rather than raising or returning 0, since 0%
    would misleadingly imply "known to break even".
    """
    if profit is None or revenue is None:
        return None
    if revenue == ZERO:
        return None
    return quantize((profit / revenue) * HUNDRED)


def calculate_estimated_profit(
    quoted_value: Decimal | None, estimated_cost: Decimal | None
) -> Decimal | None:
    """estimated_profit = quoted_value - estimated_cost"""
    return safe_subtract(quoted_value, estimated_cost)


def calculate_actual_profit(
    actual_revenue: Decimal | None, actual_cost: Decimal | None
) -> Decimal | None:
    """actual_profit = actual_revenue - actual_cost"""
    return safe_subtract(actual_revenue, actual_cost)


def calculate_estimated_margin(
    estimated_profit: Decimal | None, quoted_value: Decimal | None
) -> Decimal | None:
    """estimated_margin = estimated_profit / quoted_value * 100"""
    return safe_margin(estimated_profit, quoted_value)


def calculate_actual_margin(
    actual_profit: Decimal | None, actual_revenue: Decimal | None
) -> Decimal | None:
    """actual_margin = actual_profit / actual_revenue * 100"""
    return safe_margin(actual_profit, actual_revenue)


def calculate_actual_revenue(
    contract_value: Decimal | None, approved_variation_total: Decimal | None
) -> Decimal | None:
    """actual_revenue = contract_value + approved variations.

    A project with a contract value but no variations yet has an actual
    revenue equal to its contract value (approved_variation_total defaults
    to 0 in that case, not None) — the absence of variations is a known
    fact, unlike an unset contract value.
    """
    if contract_value is None:
        return None
    return contract_value + (approved_variation_total or ZERO)


def calculate_cost_variance(
    estimated_cost: Decimal | None, actual_cost: Decimal | None
) -> Decimal | None:
    """How much actual cost differs from estimated cost.

    Positive means the project cost more than estimated (a cost overrun).
    """
    return safe_subtract(actual_cost, estimated_cost)


class ProjectFinancials(BaseModel):
    """Aggregated financial inputs and derived figures for one project.

    Inputs are supplied by the caller (typically a service that has summed
    the relevant EstimatedCost/ActualCost/ProjectVariation rows for a
    project); this model only performs the deterministic arithmetic and
    exposes the results as computed properties, never as mutable fields, so
    they cannot drift from their inputs.
    """

    model_config = ConfigDict(frozen=True)

    currency: Currency = DEFAULT_CURRENCY
    quoted_value: Decimal | None = None
    estimated_cost: Decimal | None = None
    contract_value: Decimal | None = None
    actual_cost: Decimal | None = None
    approved_variation_total: Decimal | None = None

    @property
    def estimated_profit(self) -> Decimal | None:
        return calculate_estimated_profit(self.quoted_value, self.estimated_cost)

    @property
    def estimated_margin(self) -> Decimal | None:
        return calculate_estimated_margin(self.estimated_profit, self.quoted_value)

    @property
    def actual_revenue(self) -> Decimal | None:
        return calculate_actual_revenue(self.contract_value, self.approved_variation_total)

    @property
    def actual_profit(self) -> Decimal | None:
        return calculate_actual_profit(self.actual_revenue, self.actual_cost)

    @property
    def actual_margin(self) -> Decimal | None:
        return calculate_actual_margin(self.actual_profit, self.actual_revenue)

    @property
    def cost_variance(self) -> Decimal | None:
        return calculate_cost_variance(self.estimated_cost, self.actual_cost)
