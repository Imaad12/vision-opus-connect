"""Payments -- the frontend's `payments` module."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_finance import PaymentCreate, PaymentRead
from app.services import payment_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=list[PaymentRead])
def list_payments(
    invoice_id: int | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.payments")),
) -> list[PaymentRead]:
    return list(payment_service.list_payments(session, invoice_id=invoice_id))


@router.get("/{payment_id}", response_model=PaymentRead)
def get_payment(
    payment_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.payments")),
) -> PaymentRead:
    payment = payment_service.get_payment(session, payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found.")
    return payment


@router.post("", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.payments")),
) -> PaymentRead:
    try:
        return payment_service.create_payment(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
