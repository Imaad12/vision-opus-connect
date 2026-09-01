"""Company settings -- the frontend's `company_settings` screen, backed by
the same `Company` row the rest of the backend already uses (see
`project_service.get_or_create_default_company`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_company, get_current_user
from app.api.schemas import CompanyRead
from app.models import Company

router = APIRouter(prefix="/company", tags=["company"])


@router.get("/me", response_model=CompanyRead)
def get_my_company(
    company: Company = Depends(get_current_company),
    _user=Depends(get_current_user),
) -> Company:
    """Any authenticated user may view company settings -- this mirrors
    the frontend's `company_settings_select` RLS policy (`USING (true)`),
    which has no permission requirement beyond being signed in. Only
    *editing* company settings is gated (`admin.settings`), and that
    endpoint isn't built yet -- see API_ARCHITECTURE.md."""
    return company
