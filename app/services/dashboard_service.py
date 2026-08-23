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
from decimal import Decimal
from typing import Final

from sqlalchemy.orm import Session

from app.services.project_service import (
    ACTIVE_STATUSES,
    COMPLETED_STATUSES,
    count_active_projects,
    list_projects_with_snapshots,
)

ZERO: Final[Decimal] = Decimal("0")


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
