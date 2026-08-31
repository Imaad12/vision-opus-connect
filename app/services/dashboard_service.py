"""Portfolio-wide dashboard aggregation.

This is the only new arithmetic Phase 3 introduces: summing and averaging
figures that `app.core.financial_engine` already computed per project. No
profit/margin/variance formula is reimplemented here — this module only
combines already-correct per-project numbers across the whole portfolio.

Two different null-handling rules apply, deliberately:

- Portfolio TOTALS (money): a project with nothing recorded yet
  contributes zero to a grand total — "no cost entered on this project"
  really is zero spend on it so far, so it's correct for it to add
  nothing to "total actual cost across all projects".
- Portfolio AVERAGES (margins): a project with an undefined margin (no
  revenue yet) is excluded entirely from the average, not treated as 0%.
  Averaging in a 0% for "not applicable" would understate real
  portfolio performance and is numerically wrong, not just unhelpful.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import InvoiceDirection, LeadStatus, ProjectStatus, PurchaseOrderStatus, QuotationStatus
from app.models import Invoice, Lead, Payment, Project, PurchaseOrder, Quotation, QuotationVersion
from app.services.project_service import (
    ACTIVE_STATUSES,
    COMPLETED_STATUSES,
    count_active_projects,
    list_projects_with_snapshots,
)

ZERO: Final[Decimal] = Decimal("0")

# The frontend Dashboard page's own "not yet decided" exclusion list --
# kept as its own constant (deliberately NOT `project_service.ACTIVE_STATUSES`,
# a different, stricter definition used by `build_dashboard_summary` above)
# so this function returns exactly the same "active projects" the client
# used to compute itself from the full `/projects` list.
_DASHBOARD_INACTIVE_PROJECT_STATUSES: Final[tuple[ProjectStatus, ...]] = (
    ProjectStatus.COMPLETED,
    ProjectStatus.CLOSED,
    ProjectStatus.CANCELLED,
    ProjectStatus.LOST,
)


@dataclass(frozen=True)
class DashboardKpis:
    """One field per Dashboard KPI card. A `None` field means the caller
    lacks the permission that section requires -- distinct from a real
    zero -- so the router can omit it rather than claim "zero pipeline"
    for a user who simply can't see leads."""

    pipeline_value: Decimal | None
    awaiting_count: int | None
    awaiting_value: Decimal | None
    active_projects_count: int | None
    active_projects_value: Decimal | None
    receivables: Decimal | None
    vat_year_to_date: Decimal | None
    po_pending_count: int | None


def compute_dashboard_kpis(
    session: Session,
    *,
    include_leads: bool,
    include_quotations: bool,
    include_projects: bool,
    include_invoices: bool,
    include_purchase_orders: bool,
) -> DashboardKpis:
    """The 6 headline numbers on the Dashboard page, computed with one
    small SQL-side aggregate query per card instead of the client
    fetching entire `/leads`, `/quotations`, `/projects`, `/invoices`,
    `/purchase-orders` lists (each row-cost-modeled, some previously
    N+1-heavy) just to reduce 2-5 fields per row down to a single sum or
    count. Every filter here mirrors the client-side filter it replaces
    exactly (see `dashboard.tsx`'s pre-existing reduce/filter calls) --
    this is a relocation of arithmetic already proven correct by the
    frontend, not a new definition of any of these numbers."""

    pipeline_value = None
    if include_leads:
        pipeline_value = session.execute(
            select(func.coalesce(func.sum(Lead.estimated_value), ZERO)).where(
                Lead.is_deleted.is_(False),
                Lead.status.not_in([LeadStatus.WON, LeadStatus.LOST]),
            )
        ).scalar_one()

    awaiting_count = awaiting_value = None
    if include_quotations:
        row = session.execute(
            select(func.count(QuotationVersion.id), func.coalesce(func.sum(QuotationVersion.quoted_value), ZERO))
            .join(Quotation, QuotationVersion.quotation_id == Quotation.id)
            .where(
                QuotationVersion.is_deleted.is_(False),
                Quotation.is_deleted.is_(False),
                QuotationVersion.status == QuotationStatus.SUBMITTED,
            )
        ).one()
        awaiting_count, awaiting_value = row[0], row[1]

    active_projects_count = active_projects_value = None
    if include_projects:
        row = session.execute(
            select(func.count(Project.id), func.coalesce(func.sum(Project.contract_value), ZERO)).where(
                Project.is_deleted.is_(False),
                Project.status.not_in(_DASHBOARD_INACTIVE_PROJECT_STATUSES),
            )
        ).one()
        active_projects_count, active_projects_value = row[0], row[1]

    receivables = vat_year_to_date = None
    if include_invoices:
        invoiced_total = session.execute(
            select(func.coalesce(func.sum(Invoice.amount), ZERO)).where(
                Invoice.is_deleted.is_(False), Invoice.direction == InvoiceDirection.CLIENT
            )
        ).scalar_one()
        paid_total = session.execute(
            select(func.coalesce(func.sum(Payment.amount), ZERO))
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .where(
                Payment.is_deleted.is_(False),
                Invoice.is_deleted.is_(False),
                Invoice.direction == InvoiceDirection.CLIENT,
            )
        ).scalar_one()
        receivables = invoiced_total - paid_total

        year_start = date(date.today().year, 1, 1)
        year_end = date(date.today().year + 1, 1, 1)
        vat_year_to_date = session.execute(
            select(func.coalesce(func.sum(Invoice.tax_amount), ZERO)).where(
                Invoice.is_deleted.is_(False),
                Invoice.direction == InvoiceDirection.CLIENT,
                Invoice.issued_date.is_not(None),
                Invoice.issued_date >= year_start,
                Invoice.issued_date < year_end,
            )
        ).scalar_one()

    po_pending_count = None
    if include_purchase_orders:
        po_pending_count = session.execute(
            select(func.count(PurchaseOrder.id)).where(
                PurchaseOrder.is_deleted.is_(False),
                PurchaseOrder.status == PurchaseOrderStatus.PENDING_APPROVAL,
            )
        ).scalar_one()

    return DashboardKpis(
        pipeline_value=pipeline_value,
        awaiting_count=awaiting_count,
        awaiting_value=awaiting_value,
        active_projects_count=active_projects_count,
        active_projects_value=active_projects_value,
        receivables=receivables,
        vat_year_to_date=vat_year_to_date,
        po_pending_count=po_pending_count,
    )


@dataclass(frozen=True)
class DashboardSummary:
    total_projects: int
    active_projects: int
    completed_projects: int

    total_awarded_contract_value: Decimal
    total_invoiced_revenue: Decimal
    total_actual_cost: Decimal
    total_actual_profit: Decimal
    average_actual_margin: Decimal | None

    total_estimated_profit: Decimal
    average_estimated_margin: Decimal | None


def _average(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / len(values)


def build_dashboard_summary(session: Session) -> DashboardSummary:
    """Build the dashboard's headline figures from every non-deleted
    project's `ProjectFinancialSnapshot`."""
    pairs = list_projects_with_snapshots(session)

    total_projects = count_active_projects(session)
    active_projects = sum(1 for project, _ in pairs if project.status in ACTIVE_STATUSES)
    completed_projects = sum(1 for project, _ in pairs if project.status in COMPLETED_STATUSES)

    total_awarded_contract_value = sum(
        (snapshot.awarded_contract_value or ZERO for _, snapshot in pairs), ZERO
    )
    total_invoiced_revenue = sum((snapshot.invoiced_revenue for _, snapshot in pairs), ZERO)
    total_actual_cost = sum((snapshot.actual_cost or ZERO for _, snapshot in pairs), ZERO)
    total_actual_profit = sum((snapshot.actual_profit or ZERO for _, snapshot in pairs), ZERO)
    average_actual_margin = _average(
        [snapshot.actual_margin for _, snapshot in pairs if snapshot.actual_margin is not None]
    )

    total_estimated_profit = sum((snapshot.estimated_profit or ZERO for _, snapshot in pairs), ZERO)
    average_estimated_margin = _average(
        [snapshot.estimated_margin for _, snapshot in pairs if snapshot.estimated_margin is not None]
    )

    return DashboardSummary(
        total_projects=total_projects,
        active_projects=active_projects,
        completed_projects=completed_projects,
        total_awarded_contract_value=total_awarded_contract_value,
        total_invoiced_revenue=total_invoiced_revenue,
        total_actual_cost=total_actual_cost,
        total_actual_profit=total_actual_profit,
        average_actual_margin=average_actual_margin,
        total_estimated_profit=total_estimated_profit,
        average_estimated_margin=average_estimated_margin,
    )
