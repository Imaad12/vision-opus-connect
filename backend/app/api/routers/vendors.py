"""Suppliers/subcontractors -- the frontend's `suppliers` module, backed
by the existing `Vendor` model and `vendor_service`.

Permission names are copied verbatim from the frontend's `app_permission`
enum (`suppliers.view/create/edit`), which -- unlike the `po.*` strings
already fixed elsewhere -- genuinely exist and match.

Known gap, deliberately not papered over: the frontend's `suppliers.tsx`
form also collects `category`, `cr_number`, `city`, `payment_terms_days`
(a number of days; the backend has a free-text `payment_terms` instead),
`rating`, a three-state `status` (active/inactive/blacklisted; the
backend has a boolean `is_active`), `iban`, `address`, and `name_ar`.
None of these exist on `Vendor` today. Adding them to make the existing
frontend form "just work" would be inventing backend fields to fit a UI,
which we were explicitly told not to do -- so this API exposes exactly
what `Vendor` has, and wiring the frontend's supplier *form* to it is
left as a follow-up that needs one of two real decisions: extend
`Vendor` with the missing columns, or trim the frontend form to match.
Read-only wiring (list/detail) has no such conflict.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas import VendorCreate, VendorRead, VendorUpdate
from app.services import vendor_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=list[VendorRead])
def list_vendors(
    search: str | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("suppliers.view")),
) -> list[VendorRead]:
    return list(vendor_service.list_vendors(session, search=search))


@router.get("/{vendor_id}", response_model=VendorRead)
def get_vendor(
    vendor_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("suppliers.view")),
) -> VendorRead:
    vendor = vendor_service.get_vendor(session, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found.")
    return vendor


@router.post("", response_model=VendorRead, status_code=status.HTTP_201_CREATED)
def create_vendor(
    payload: VendorCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("suppliers.create")),
) -> VendorRead:
    try:
        return vendor_service.create_vendor(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{vendor_id}", response_model=VendorRead)
def update_vendor(
    vendor_id: int,
    payload: VendorUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("suppliers.edit")),
) -> VendorRead:
    vendor = vendor_service.get_vendor(session, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found.")
    try:
        return vendor_service.update_vendor(session, vendor, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
