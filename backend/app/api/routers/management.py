"""Management/reporting endpoints (Milestone 3).

`GET /management/dashboard-summary` is open to any authenticated user --
same rule as `GET /company/me` -- since it is a portfolio headline count,
not a financial detail. Everything else here is real financial detail
(project profitability, vendor payables, cash flow, operating income) and
is gated on `finance.reports`, the real `app_permission` enum value the
frontend nav already uses as the read-access grant for finance reporting
views (see `nav.invoices`/`nav.payments`/`nav.expenses`/`nav.vat` in
app-shell.tsx, which all already accept `finance.reports` as an
alternative to their own domain permission).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_permission
from app.api.schemas_management import (
    CashFlowSummaryRead,
    DashboardSummaryRead,
    OperatingIncomeSummaryRead,
    ProjectProfitabilityRead,
    VendorSpendRead,
)
from app.services import dashboard_service, management_service

router = APIRouter(prefix="/management", tags=["management"])


@router.get("/dashboard-summary", response_model=DashboardSummaryRead)
def get_dashboard_summary(
    session: Session = Depends(get_db),
    _user=Depends(get_current_user),
) -> DashboardSummaryRead:
    return dashboard_service.build_dashboard_summary(session)


@router.get("/project-profitability", response_model=list[ProjectProfitabilityRead])
def get_project_profitability(
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.reports")),
) -> list[ProjectProfitabilityRead]:
    return list(management_service.compute_project_profitability(session))


@router.get("/vendor-spend", response_model=list[VendorSpendRead])
def get_vendor_spend(
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.reports")),
) -> list[VendorSpendRead]:
    return list(management_service.compute_vendor_spend(session))


@router.get("/cash-flow", response_model=CashFlowSummaryRead)
def get_cash_flow(
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.reports")),
) -> CashFlowSummaryRead:
    return management_service.compute_cash_flow_summary(session)


@router.get("/operating-income", response_model=OperatingIncomeSummaryRead)
def get_operating_income(
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.reports")),
) -> OperatingIncomeSummaryRead:
    return management_service.compute_operating_income(session)
