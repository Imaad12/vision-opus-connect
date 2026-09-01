"""`GET /dashboard/summary` -- the 6 KPI cards on the frontend's Dashboard
page, computed server-side.

Before this endpoint existed, the Dashboard page fetched the entire
`/leads`, `/quotations`, `/projects`, `/invoices`, and `/purchase-orders`
lists (each row carrying every field that endpoint's other consumers
need -- e.g. `PurchaseOrderRead` embeds the full vendor, project, and line
items) just to reduce 2-5 fields per row down to a single sum or count in
the browser. This endpoint runs the same reductions as one small SQL
aggregate query per card instead, cutting both the number of requests and
the bytes transferred for this part of the page -- confirmed, evidence-
driven per the VINCO performance audit, not a speculative addition.

Every existing list endpoint (`/leads`, `/quotations`, `/projects`,
`/invoices`, `/purchase-orders`) is untouched and still used by every
other page that needs full rows (Approvals, Quotations, Purchase Orders,
Contracts, Management) -- this is purely additive, so no other page's
behavior or API contract changes.

Authorization is per-card, not per-endpoint: a user with only some of
`leads.view`/`quotations.view`/`projects.view`/`finance.invoices`-or-
`finance.reports`/`purchasing.po_approve`-or-`purchasing.po_create` gets
those cards computed and the rest returned as `null` -- exactly mirroring
what `dashboard.tsx`'s own `me.can(...)` gates already decide about which
`useQuery`s to even enable, never widening what any user can see.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedUser, AuthError, SupabaseAuth
from app.api.deps import get_current_user, get_db, get_supabase_auth
from app.api.permission_cache import get_cached_permission, set_cached_permission
from app.api.schemas_management import DashboardKpisRead
from app.api.timing import timed
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _can(user: AuthenticatedUser, auth: SupabaseAuth, permission: str) -> bool:
    """Same cache-then-Supabase-`can()` decision `require_permission` makes
    for a single required permission, but returning a bool instead of
    raising -- this endpoint needs several independent yes/no answers in
    one request, not one all-or-nothing gate."""
    allowed = get_cached_permission(user.id, permission)
    if allowed is None:
        try:
            with timed("rbac"):
                allowed = auth.check_permission(user, permission)
        except AuthError:
            allowed = False
        set_cached_permission(user.id, permission, allowed)
    return allowed


@router.get("/summary", response_model=DashboardKpisRead)
def get_dashboard_summary(
    session: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
    auth: SupabaseAuth = Depends(get_supabase_auth),
) -> DashboardKpisRead:
    can_leads = _can(user, auth, "leads.view")
    can_quotations = _can(user, auth, "quotations.view")
    can_projects = _can(user, auth, "projects.view")
    can_invoices = _can(user, auth, "finance.invoices") or _can(user, auth, "finance.reports")
    can_purchase_orders = _can(user, auth, "purchasing.po_approve") or _can(
        user, auth, "purchasing.po_create"
    )

    kpis = dashboard_service.compute_dashboard_kpis(
        session,
        include_leads=can_leads,
        include_quotations=can_quotations,
        include_projects=can_projects,
        include_invoices=can_invoices,
        include_purchase_orders=can_purchase_orders,
    )
    return DashboardKpisRead.model_validate(kpis)
