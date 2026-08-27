"""Supplier Purchase Orders -- backed entirely by `purchase_order_service`.

This is the real ERP supplier-PO concept the VINCO frontend's existing
Purchase Orders page is about; not to be confused with the (renamed)
`ClientAwardEvidence` concept, which has no route under `/purchase-orders`
at all any more.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_procurement import (
    PurchaseOrderCreate,
    PurchaseOrderLinesUpdate,
    PurchaseOrderRead,
)
from app.services import purchase_order_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/purchase-orders", tags=["procurement"])


def _get_or_404(session: Session, purchase_order_id: int):
    po = purchase_order_service.get_purchase_order(session, purchase_order_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found.")
    return po


@router.get("", response_model=list[PurchaseOrderRead])
def list_purchase_orders(
    project_id: int | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_create")),
) -> list[PurchaseOrderRead]:
    return list(purchase_order_service.list_purchase_orders(session, project_id=project_id))


@router.get("/{purchase_order_id}", response_model=PurchaseOrderRead)
def get_purchase_order(
    purchase_order_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_create")),
) -> PurchaseOrderRead:
    return _get_or_404(session, purchase_order_id)


@router.post("", response_model=PurchaseOrderRead, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    payload: PurchaseOrderCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_create")),
) -> PurchaseOrderRead:
    try:
        return purchase_order_service.create_purchase_order(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{purchase_order_id}/lines", response_model=PurchaseOrderRead)
def set_purchase_order_lines(
    purchase_order_id: int,
    payload: PurchaseOrderLinesUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_create")),
) -> PurchaseOrderRead:
    po = _get_or_404(session, purchase_order_id)
    try:
        return purchase_order_service.set_purchase_order_lines(
            session, po, [line.model_dump() for line in payload.lines]
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{purchase_order_id}/submit", response_model=PurchaseOrderRead)
def submit_purchase_order(
    purchase_order_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_create")),
) -> PurchaseOrderRead:
    po = _get_or_404(session, purchase_order_id)
    try:
        return purchase_order_service.submit_purchase_order(session, po)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{purchase_order_id}/approve", response_model=PurchaseOrderRead)
def approve_purchase_order(
    purchase_order_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_approve")),
) -> PurchaseOrderRead:
    po = _get_or_404(session, purchase_order_id)
    try:
        return purchase_order_service.approve_purchase_order(session, po)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{purchase_order_id}/reject", response_model=PurchaseOrderRead)
def reject_purchase_order(
    purchase_order_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_approve")),
) -> PurchaseOrderRead:
    po = _get_or_404(session, purchase_order_id)
    try:
        return purchase_order_service.reject_purchase_order(session, po)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{purchase_order_id}/cancel", response_model=PurchaseOrderRead)
def cancel_purchase_order(
    purchase_order_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_approve")),
) -> PurchaseOrderRead:
    po = _get_or_404(session, purchase_order_id)
    try:
        return purchase_order_service.cancel_purchase_order(session, po)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
