"""Receiving against a supplier Purchase Order -- backed entirely by
`receipt_service`. No warehouse/inventory concepts here, per
API_ARCHITECTURE.md -- a receipt only ever updates the referenced PO's
line `received_quantity` and status.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_procurement import ReceiptCreate, ReceiptRead
from app.services import purchase_order_service, receipt_service
from app.services.errors import ValidationError

router = APIRouter(tags=["procurement"])


def _get_receipt_or_404(session: Session, receipt_id: int):
    receipt = receipt_service.get_receipt(session, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found.")
    return receipt


@router.get("/purchase-orders/{purchase_order_id}/receipts", response_model=list[ReceiptRead])
def list_receipts(
    purchase_order_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.receive")),
) -> list[ReceiptRead]:
    po = purchase_order_service.get_purchase_order(session, purchase_order_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found.")
    return list(receipt_service.list_receipts_for_purchase_order(session, purchase_order_id))


@router.get("/receipts/{receipt_id}", response_model=ReceiptRead)
def get_receipt(
    receipt_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.receive")),
) -> ReceiptRead:
    return _get_receipt_or_404(session, receipt_id)


@router.post(
    "/purchase-orders/{purchase_order_id}/receipts",
    response_model=ReceiptRead,
    status_code=status.HTTP_201_CREATED,
)
def create_receipt(
    purchase_order_id: int,
    payload: ReceiptCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.receive")),
) -> ReceiptRead:
    po = purchase_order_service.get_purchase_order(session, purchase_order_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found.")
    try:
        return receipt_service.create_receipt(
            session,
            po,
            receipt_date=payload.receipt_date,
            lines=[line.model_dump() for line in payload.lines],
            received_by=payload.received_by,
            notes=payload.notes,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/receipts/{receipt_id}/cancel", response_model=ReceiptRead)
def cancel_receipt(
    receipt_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.receive")),
) -> ReceiptRead:
    receipt = _get_receipt_or_404(session, receipt_id)
    try:
        return receipt_service.cancel_receipt(session, receipt)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
