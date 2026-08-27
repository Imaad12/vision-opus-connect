"""Read-only lookup endpoints for UI selectors."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_finance import CostCategoryRead
from app.services import lookup_service

router = APIRouter(prefix="/cost-categories", tags=["lookups"])


@router.get("", response_model=list[CostCategoryRead])
def list_cost_categories(
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.expenses")),
) -> list[CostCategoryRead]:
    return list(lookup_service.list_cost_categories(session))
