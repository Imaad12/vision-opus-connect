"""Estimated-cost and actual-cost management.

Estimated costs are always attached to an `EstimateRevision` (see
`app.services.financial_service` for revision lookup/creation). Only the
LATEST revision may be added to or edited from the UI — everything else is
history and is exposed read-only, which is what actually prevents a user
from "accidentally overwriting historical estimate records" (the DB
constraint alone doesn't stop an edit to an old row; this module does).

Actual costs are completely separate rows (`ActualCost`) and never
interact with `EstimatedCost` at all.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.enums import DEFAULT_CURRENCY, CostPaymentStatus, Currency
from app.core.financial_engine import calculate_line_total, calculate_net_of_tax, calculate_recognized_cost
from app.models import ActualCost, CostCategory, EstimatedCost, EstimateRevision, Project
from app.services.errors import ValidationError
from app.services.financial_service import (
    create_estimate_revision,
    get_latest_estimate_revision,
    get_original_estimate_revision,
    list_estimate_revisions,
)

# --- Estimated costs -------------------------------------------------------


def get_or_create_current_revision(session: Session, project: Project) -> EstimateRevision:
    """The revision new estimate lines should be added to: the latest one,
    creating revision 1 automatically if the project has none yet."""
    latest = get_latest_estimate_revision(session, project)
    if latest is not None:
        return latest
    return create_estimate_revision(session, project)


def list_estimated_costs(session: Session, revision: EstimateRevision) -> list[EstimatedCost]:
    stmt = (
        select(EstimatedCost)
        .options(joinedload(EstimatedCost.cost_category))
        .where(EstimatedCost.estimate_revision_id == revision.id, EstimatedCost.is_deleted.is_(False))
        .order_by(EstimatedCost.id)
    )
    return list(session.execute(stmt).scalars().all())


def _resolved_amount(quantity: Decimal | None, unit_rate: Decimal | None, amount: Decimal | None) -> Decimal:
    if amount is not None:
        return amount
    computed = calculate_line_total(quantity, unit_rate)
    if computed is None:
        raise ValidationError("Enter either an amount, or both quantity and unit rate.")
    return computed


def add_estimated_cost_line(
    session: Session,
    project: Project,
    revision: EstimateRevision,
    *,
    cost_category_id: int,
    description: str | None = None,
    quantity: Decimal | None = None,
    unit: str | None = None,
    unit_rate: Decimal | None = None,
    amount: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    notes: str | None = None,
) -> EstimatedCost:
    latest = get_latest_estimate_revision(session, project)
    if latest is None or revision.id != latest.id:
        raise ValidationError(
            "This is a historical estimate revision and cannot be edited. Start a new revision instead."
        )
    if cost_category_id is None or session.get(CostCategory, cost_category_id) is None:
        raise ValidationError("Select a valid cost category.")

    resolved_amount = _resolved_amount(quantity, unit_rate, amount)

    line = EstimatedCost(
        project_id=project.id,
        estimate_revision_id=revision.id,
        cost_category_id=cost_category_id,
        description=(description or "").strip() or None,
        quantity=quantity,
        unit=(unit or "").strip() or None,
        unit_rate=unit_rate,
        amount=resolved_amount,
        currency=currency,
        notes=(notes or "").strip() or None,
    )
    session.add(line)
    session.flush()
    return line


def remove_estimated_cost_line(session: Session, project: Project, line: EstimatedCost) -> None:
    """Soft-delete a line — only permitted on the current (latest) revision;
    historical revisions are never modified, including by deletion."""
    latest = get_latest_estimate_revision(session, project)
    if latest is None or line.estimate_revision_id != latest.id:
        raise ValidationError("Historical estimate lines cannot be removed.")
    line.is_deleted = True
    session.flush()


def start_new_estimate_revision(
    session: Session,
    project: Project,
    *,
    effective_date: date | None = None,
    is_final: bool = False,
    notes: str | None = None,
    copy_forward: bool = True,
) -> EstimateRevision:
    """Start a new estimate revision. By default, copies the current
    revision's lines forward as a starting point for editing (each copied
    line is a brand-new row — the source revision's rows are untouched),
    since re-estimating from scratch every time would make revisions
    impractical to use. Pass `copy_forward=False` for a blank revision.
    """
    previous = get_latest_estimate_revision(session, project)

    if is_final:
        _clear_existing_final_flag(session, project)

    revision = create_estimate_revision(
        session,
        project,
        effective_date=effective_date,
        is_final=is_final,
        notes=notes,
    )

    if copy_forward and previous is not None:
        for line in list_estimated_costs(session, previous):
            session.add(
                EstimatedCost(
                    project_id=project.id,
                    estimate_revision_id=revision.id,
                    cost_category_id=line.cost_category_id,
                    trade_id=line.trade_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_rate=line.unit_rate,
                    amount=line.amount,
                    currency=line.currency,
                    notes=line.notes,
                )
            )
        session.flush()

    return revision


def mark_revision_final(session: Session, project: Project, revision: EstimateRevision) -> EstimateRevision:
    _clear_existing_final_flag(session, project)
    revision.is_final = True
    session.flush()
    return revision


def _clear_existing_final_flag(session: Session, project: Project) -> None:
    stmt = select(EstimateRevision).where(
        EstimateRevision.project_id == project.id,
        EstimateRevision.is_final.is_(True),
        EstimateRevision.is_deleted.is_(False),
    )
    for existing_final in session.execute(stmt).scalars().all():
        existing_final.is_final = False
    session.flush()


# --- Actual costs ------------------------------------------------------------


def list_actual_costs(session: Session, project: Project) -> list[ActualCost]:
    stmt = (
        select(ActualCost)
        .options(joinedload(ActualCost.cost_category), joinedload(ActualCost.vendor))
        .where(ActualCost.project_id == project.id, ActualCost.is_deleted.is_(False))
        .order_by(ActualCost.incurred_date.desc().nulls_last(), ActualCost.id.desc())
    )
    return list(session.execute(stmt).scalars().all())


def add_actual_cost(
    session: Session,
    project: Project,
    *,
    cost_category_id: int,
    amount: Decimal,
    tax_amount: Decimal | None = None,
    is_tax_recoverable: bool = True,
    incurred_date: date | None = None,
    description: str | None = None,
    vendor_id: int | None = None,
    reference_number: str | None = None,
    payment_status: CostPaymentStatus = CostPaymentStatus.UNPAID,
    currency: Currency = DEFAULT_CURRENCY,
    notes: str | None = None,
) -> ActualCost:
    if cost_category_id is None or session.get(CostCategory, cost_category_id) is None:
        raise ValidationError("Select a valid cost category.")
    if amount is None:
        raise ValidationError("Gross amount is required.")
    if tax_amount is not None and abs(tax_amount) > abs(amount):
        raise ValidationError("Tax amount cannot exceed the gross amount.")

    cost = ActualCost(
        project_id=project.id,
        cost_category_id=cost_category_id,
        vendor_id=vendor_id,
        reference_number=(reference_number or "").strip() or None,
        description=(description or "").strip() or None,
        amount=amount,
        tax_amount=tax_amount,
        is_tax_recoverable=is_tax_recoverable,
        currency=currency,
        payment_status=payment_status,
        incurred_date=incurred_date,
        notes=(notes or "").strip() or None,
    )
    session.add(cost)
    session.flush()
    return cost


def cost_by_category(session: Session, project: Project) -> list[tuple[CostCategory, Decimal]]:
    """Recognized actual cost (tax-adjusted, per `calculate_recognized_cost`)
    grouped by category, largest first. A small, in-Python grouping — fine
    at this application's scale, and it avoids reimplementing the
    recoverable-tax rule as a second, SQL-side version of the same logic.
    """
    costs = list_actual_costs(session, project)
    totals: dict[int, Decimal] = {}
    categories: dict[int, CostCategory] = {}
    for cost in costs:
        recognized = calculate_recognized_cost(cost.amount, cost.tax_amount, cost.is_tax_recoverable)
        if recognized is None:
            continue
        totals[cost.cost_category_id] = totals.get(cost.cost_category_id, Decimal("0")) + recognized
        categories.setdefault(cost.cost_category_id, cost.cost_category)

    return sorted(
        ((categories[category_id], total) for category_id, total in totals.items()),
        key=lambda pair: pair[1],
        reverse=True,
    )


def net_amount_of(cost: ActualCost) -> Decimal | None:
    """Convenience for display: the tax-exclusive value of one ActualCost row."""
    return calculate_net_of_tax(cost.amount, cost.tax_amount)


__all__ = [
    "get_or_create_current_revision",
    "get_original_estimate_revision",
    "get_latest_estimate_revision",
    "list_estimate_revisions",
    "list_estimated_costs",
    "add_estimated_cost_line",
    "remove_estimated_cost_line",
    "start_new_estimate_revision",
    "mark_revision_final",
    "list_actual_costs",
    "add_actual_cost",
    "cost_by_category",
    "net_amount_of",
]
