"""Deterministic financial calculations.

Every function here is a pure function over `Decimal` inputs. There is no
database access, no I/O, and no AI in this module — profit and margin
figures must be reproducible and auditable, so they are computed the same
way every time from the same inputs.

Do not add any code path here (or anywhere else) that lets a language
model output feed into these calculations as a number. AI may later read
the *results* of this module to generate commentary, but it never computes
or overrides them.

See FINANCIAL_MODEL.md for the full narrative definitions and worked
examples. In short, there are three stages of "profit," each with its own
revenue basis, and mixing them up is the most common way a profit figure
becomes wrong:

1. QUOTED (pre-award, a bid/no-bid decision tool):
   quoted_profit  = quoted_value - estimated_cost
   quoted_margin  = quoted_profit / quoted_value * 100

2. ESTIMATED (post-award, using the agreed contract terms):
   estimated_profit = awarded_contract_value - estimated_cost
   estimated_margin = estimated_profit / awarded_contract_value * 100

3. ACTUAL (during/after execution, using real recorded figures):
   actual_revenue = revised_contract_value
                   = awarded_contract_value + approved_variation_value
   actual_profit  = actual_revenue - actual_cost
   actual_margin  = actual_profit / actual_revenue * 100

`awarded_contract_value` is always the ORIGINAL value agreed at award and
must never be mutated when a variation is approved; `revised_contract_value`
is the live, computed figure that includes approved variations. Neither is
ever the same thing as "invoiced revenue" (what's actually been billed) or
"cash received" (what's actually been collected) — see the invoice-level
functions below and FINANCIAL_MODEL.md.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DEFAULT_CURRENCY, Currency, ProjectStatus
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
    would misleadingly imply "known to break even". This is the only place
    in the engine where rounding happens: the result is quantized to 2
    decimal places (ROUND_HALF_UP) because division can produce more
    precision than a percentage figure should display. See
    FINANCIAL_MODEL.md "Rounding rules".
    """
    if profit is None or revenue is None:
        return None
    if revenue == ZERO:
        return None
    return quantize((profit / revenue) * HUNDRED)


# --- Stage 1: Quoted (pre-award) ---------------------------------------


def calculate_quoted_profit(quoted_value: Decimal | None, estimated_cost: Decimal | None) -> Decimal | None:
    """quoted_profit = quoted_value - estimated_cost

    A pre-award bid/no-bid figure: what profit this quote would yield
    against the current cost estimate, before any award has happened.
    """
    return safe_subtract(quoted_value, estimated_cost)


def calculate_quoted_margin(
    quoted_profit: Decimal | None, quoted_value: Decimal | None
) -> Decimal | None:
    """quoted_margin = quoted_profit / quoted_value * 100"""
    return safe_margin(quoted_profit, quoted_value)


# --- Stage 2: Estimated (post-award) ------------------------------------


def calculate_estimated_profit(
    awarded_contract_value: Decimal | None, estimated_cost: Decimal | None
) -> Decimal | None:
    """estimated_profit = awarded_contract_value - estimated_cost

    Uses the AWARDED contract value (the value actually agreed, which may
    differ from the original quote after negotiation) — never the quoted
    value. Use `calculate_quoted_profit` for the pre-award figure instead
    of substituting quoted_value here.
    """
    return safe_subtract(awarded_contract_value, estimated_cost)


def calculate_estimated_margin(
    estimated_profit: Decimal | None, awarded_contract_value: Decimal | None
) -> Decimal | None:
    """estimated_margin = estimated_profit / awarded_contract_value * 100"""
    return safe_margin(estimated_profit, awarded_contract_value)


# --- Stage 3: Actual (during/after execution) ---------------------------


def calculate_revised_contract_value(
    awarded_contract_value: Decimal | None, approved_variation_value: Decimal | None
) -> Decimal | None:
    """revised_contract_value = awarded_contract_value + approved_variation_value

    Only APPROVED variations may be included in `approved_variation_value`
    — the caller is responsible for excluding PROPOSED/PENDING_APPROVAL/
    REJECTED/CANCELLED variations before summing (a pending variation must
    never affect contract revenue).

    A project with an awarded contract value but no approved variations
    yet has a revised value equal to the awarded value
    (`approved_variation_value` defaults to 0 in that case, not None) — the
    absence of approved variations is a known fact, unlike an unset
    contract value. This value doubles as "actual revenue" for the profit
    calculations below; see `calculate_actual_revenue`.
    """
    if awarded_contract_value is None:
        return None
    return awarded_contract_value + (approved_variation_value or ZERO)


def calculate_actual_revenue(
    contract_value: Decimal | None, approved_variation_total: Decimal | None
) -> Decimal | None:
    """actual_revenue = revised_contract_value.

    This is the accrual/earned-value figure — what the company is entitled
    to for the contract as it currently stands. It is deliberately not the
    same thing as "invoiced revenue" (the sum of client invoices actually
    raised so far, which may lag behind this figure on an in-progress
    project) or "cash received" (the sum of payments actually collected,
    which additionally lags invoiced revenue by whatever is unpaid or held
    as retention). All three are legitimate, differently-named figures;
    conflating them is the most common way a profit figure becomes wrong.

    This is an alias of `calculate_revised_contract_value`, kept as a
    separate name because both "actual revenue" and "revised contract
    value" are used in different parts of the business vocabulary for the
    exact same figure.
    """
    return calculate_revised_contract_value(contract_value, approved_variation_total)


def calculate_actual_profit(actual_revenue: Decimal | None, actual_cost: Decimal | None) -> Decimal | None:
    """actual_profit = actual_revenue - actual_cost"""
    return safe_subtract(actual_revenue, actual_cost)


def calculate_actual_margin(
    actual_profit: Decimal | None, actual_revenue: Decimal | None
) -> Decimal | None:
    """actual_margin = actual_profit / actual_revenue * 100"""
    return safe_margin(actual_profit, actual_revenue)


# --- Variances ------------------------------------------------------------
#
# Every variance follows the same "actual minus baseline" convention: a
# positive cost variance means costs ran over; a positive revenue/profit/
# margin variance means the project outperformed its baseline.


def calculate_cost_variance(estimated_cost: Decimal | None, actual_cost: Decimal | None) -> Decimal | None:
    """cost_variance = actual_cost - estimated_cost (positive = overrun)."""
    return safe_subtract(actual_cost, estimated_cost)


def calculate_revenue_variance(
    contract_revenue: Decimal | None, actual_revenue: Decimal | None
) -> Decimal | None:
    """revenue_variance = actual_revenue - contract_revenue.

    `contract_revenue` is the awarded (original) contract value; since
    `actual_revenue` already equals `contract_revenue + approved
    variations`, this variance is simply the net effect of approved
    variations on revenue.
    """
    return safe_subtract(actual_revenue, contract_revenue)


def calculate_profit_variance(
    estimated_profit: Decimal | None, actual_profit: Decimal | None
) -> Decimal | None:
    """profit_variance = actual_profit - estimated_profit."""
    return safe_subtract(actual_profit, estimated_profit)


def calculate_margin_variance(
    estimated_margin: Decimal | None, actual_margin: Decimal | None
) -> Decimal | None:
    """margin_variance = actual_margin - estimated_margin (percentage points)."""
    return safe_subtract(actual_margin, estimated_margin)


# --- Invoice/cost-level pass-through calculations (VAT, retention) ------
#
# An invoice's or cost's face value is never itself "revenue" or "cost"
# without first removing the parts that are not the company's money: VAT
# collected on the government's behalf (a pass-through liability, not
# profit) and retention withheld by the counterparty (money earned but not
# yet collectible). Getting these wrong is the classic way tax accidentally
# inflates a profit figure.


def calculate_net_of_tax(gross_amount: Decimal | None, tax_amount: Decimal | None) -> Decimal | None:
    """The tax-exclusive value of an amount: gross_amount - tax_amount.

    A missing `tax_amount` is treated as zero (no VAT recorded), but a
    missing `gross_amount` means the amount itself is unknown, so the
    result is None rather than 0.
    """
    if gross_amount is None:
        return None
    return gross_amount - (tax_amount or ZERO)


def calculate_gross_amount(net_amount: Decimal | None, tax_amount: Decimal | None) -> Decimal | None:
    """The tax-inclusive value of an amount: net_amount + tax_amount.

    The inverse of `calculate_net_of_tax`. A missing `tax_amount` is
    treated as zero; a missing `net_amount` means the result is unknown.
    """
    if net_amount is None:
        return None
    return net_amount + (tax_amount or ZERO)


def calculate_amount_due_after_retention(
    invoice_amount: Decimal | None, retention_amount: Decimal | None
) -> Decimal | None:
    """The amount currently payable/collectible on an invoice, excluding
    whatever portion is being held back as retention.

    This is distinct from `calculate_net_of_tax`: retention is withheld
    from the invoice's face value (which normally includes tax), it does
    not remove tax from the calculation. Retention withheld is still
    invoiced revenue — it is simply not yet collectible cash.
    """
    if invoice_amount is None:
        return None
    return invoice_amount - (retention_amount or ZERO)


def calculate_outstanding_balance(
    amount_due: Decimal | None, amount_paid: Decimal | None
) -> Decimal | None:
    """How much of an amount due remains unpaid: amount_due - amount_paid.

    A missing `amount_paid` is treated as zero (nothing collected yet, a
    known fact); a missing `amount_due` means the obligation itself is
    unknown, so the result is None. A negative result means the amount due
    has been overpaid. Cash received is never itself treated as revenue —
    it is only ever compared against an already-established amount due.
    """
    if amount_due is None:
        return None
    return amount_due - (amount_paid or ZERO)


def calculate_recognized_cost(
    gross_amount: Decimal | None,
    tax_amount: Decimal | None,
    is_tax_recoverable: bool = True,
) -> Decimal | None:
    """The amount of an ActualCost that counts as project cost.

    VAT/tax is excluded from project cost by default (`is_tax_recoverable
    =True`), since reclaimable input VAT is not a real cost to the
    business — the recognized cost is then the net (tax-exclusive) amount.
    When tax is explicitly marked non-recoverable (e.g. blocked input VAT),
    the business genuinely bears the full gross amount, so the recognized
    cost is the gross amount instead.
    """
    if gross_amount is None:
        return None
    if is_tax_recoverable:
        return calculate_net_of_tax(gross_amount, tax_amount)
    return gross_amount


def calculate_line_total(quantity: Decimal | None, unit_rate: Decimal | None) -> Decimal | None:
    """line_total = quantity * unit_rate, rounded to 2 decimal places.

    Used to keep an EstimatedCost/BOQLineItem's stored total in sync with
    its quantity and unit rate (by the service layer, not a DB trigger —
    see DATABASE_SCHEMA.md). Multiplying a 3-decimal quantity by a
    2-decimal rate can produce more than 2 decimal places, so this is one
    of the two places in the engine where rounding is applied (the other
    being `safe_margin`); see FINANCIAL_MODEL.md "Rounding rules".
    """
    if quantity is None or unit_rate is None:
        return None
    return quantize(quantity * unit_rate)


class ProjectFinancialSnapshot(BaseModel):
    """A complete, point-in-time financial picture of one project.

    Every field here is either a plain input — supplied by the caller
    (typically `app.services.financial_service.build_project_financial_snapshot`,
    which sums the relevant EstimatedCost/ActualCost/ProjectVariation/
    Invoice/Payment rows for a project) — or a `@property` computed purely
    from those inputs via the functions above. Nothing computed is ever
    also stored as a plain field, so a snapshot can never disagree with
    itself. Instances are immutable (`frozen=True`).

    Field-naming follows the project's financial vocabulary exactly (see
    FINANCIAL_MODEL.md): `awarded_contract_value` is the ORIGINAL value
    agreed at award; `revised_contract_value` (aliased as `actual_revenue`)
    includes approved variations; `invoiced_revenue` is already net of VAT
    (see `invoiced_revenue_gross` for the face-value total actually
    billed).
    """

    model_config = ConfigDict(frozen=True)

    currency: Currency = DEFAULT_CURRENCY
    project_status: ProjectStatus | None = Field(
        default=None,
        description="Informational only — the engine never branches on this; "
        "it exists so a LOST/CANCELLED project's numbers are always shown "
        "alongside their true status rather than implying completed work.",
    )

    # Stage 1: quoted
    quoted_value: Decimal | None = None

    # Cost estimate (a single current figure feeds both stage 1 and stage 2 —
    # see FINANCIAL_MODEL.md for why there is only one estimated_cost input)
    estimated_cost: Decimal | None = None

    # Stage 2: awarded/estimated
    awarded_contract_value: Decimal | None = None
    approved_variation_value: Decimal | None = None

    # Stage 3: actual
    actual_cost: Decimal | None = None

    # Invoicing and cash collection (aggregated by the service layer from
    # Invoice/Payment rows; these are transactional sums, not judgment-based
    # estimates, so an empty transaction history is a true zero, not
    # "unknown" — see FINANCIAL_MODEL.md)
    invoiced_revenue: Decimal = Field(
        default=ZERO, description="Sum of client invoices raised, net of VAT."
    )
    invoiced_revenue_gross: Decimal = Field(
        default=ZERO, description="Sum of client invoices raised, inclusive of VAT."
    )
    retention_outstanding: Decimal = Field(
        default=ZERO, description="Retention withheld to date minus retention released to date."
    )
    receivables_outstanding: Decimal = Field(
        default=ZERO, description="Amount currently due (after retention) minus cash received."
    )
    cash_received: Decimal = Field(default=ZERO, description="Sum of payments actually collected.")

    @property
    def quoted_profit(self) -> Decimal | None:
        return calculate_quoted_profit(self.quoted_value, self.estimated_cost)

    @property
    def quoted_margin(self) -> Decimal | None:
        return calculate_quoted_margin(self.quoted_profit, self.quoted_value)

    @property
    def estimated_profit(self) -> Decimal | None:
        return calculate_estimated_profit(self.awarded_contract_value, self.estimated_cost)

    @property
    def estimated_margin(self) -> Decimal | None:
        return calculate_estimated_margin(self.estimated_profit, self.awarded_contract_value)

    @property
    def revised_contract_value(self) -> Decimal | None:
        return calculate_revised_contract_value(
            self.awarded_contract_value, self.approved_variation_value
        )

    @property
    def actual_revenue(self) -> Decimal | None:
        """Alias of `revised_contract_value` — see the module docstring."""
        return self.revised_contract_value

    @property
    def actual_profit(self) -> Decimal | None:
        return calculate_actual_profit(self.actual_revenue, self.actual_cost)

    @property
    def actual_margin(self) -> Decimal | None:
        return calculate_actual_margin(self.actual_profit, self.actual_revenue)

    @property
    def cost_variance(self) -> Decimal | None:
        return calculate_cost_variance(self.estimated_cost, self.actual_cost)

    @property
    def revenue_variance(self) -> Decimal | None:
        return calculate_revenue_variance(self.awarded_contract_value, self.actual_revenue)

    @property
    def profit_variance(self) -> Decimal | None:
        return calculate_profit_variance(self.estimated_profit, self.actual_profit)

    @property
    def margin_variance(self) -> Decimal | None:
        return calculate_margin_variance(self.estimated_margin, self.actual_margin)
