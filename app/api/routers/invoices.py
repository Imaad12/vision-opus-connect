"""Invoices -- the frontend's `invoices` module. Permission name
(`finance.invoices`) is copied verbatim from the frontend's
`app_permission` enum, which has no finer view/create/edit split for
finance, unlike customers/vendors."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_finance import InvoiceCreate, InvoiceRead, InvoiceUpdate
from app.models import Invoice
from app.services import invoice_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _to_read(session: Session, invoice: Invoice) -> InvoiceRead:
    data = InvoiceRead.model_validate(invoice)
    data.amount_paid = invoice_service.amount_paid(session, invoice)
    return data


@router.get("", response_model=list[InvoiceRead])
def list_invoices(
    project_id: int | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.invoices")),
) -> list[InvoiceRead]:
    invoices = invoice_service.list_invoices(session, project_id=project_id)
    return [_to_read(session, i) for i in invoices]


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(
    invoice_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.invoices")),
) -> InvoiceRead:
    invoice = invoice_service.get_invoice(session, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    return _to_read(session, invoice)


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
def create_invoice(
    payload: InvoiceCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.invoices")),
) -> InvoiceRead:
    try:
        invoice = invoice_service.create_invoice(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_read(session, invoice)


@router.put("/{invoice_id}", response_model=InvoiceRead)
def update_invoice(
    invoice_id: int,
    payload: InvoiceUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.invoices")),
) -> InvoiceRead:
    invoice = invoice_service.get_invoice(session, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    try:
        invoice = invoice_service.update_invoice(session, invoice, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_read(session, invoice)


@router.post("/{invoice_id}/issue", response_model=InvoiceRead)
def issue_invoice(
    invoice_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.invoices")),
) -> InvoiceRead:
    invoice = invoice_service.get_invoice(session, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    try:
        invoice = invoice_service.issue_invoice(session, invoice)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_read(session, invoice)


@router.post("/{invoice_id}/cancel", response_model=InvoiceRead)
def cancel_invoice(
    invoice_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.invoices")),
) -> InvoiceRead:
    invoice = invoice_service.get_invoice(session, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    try:
        invoice = invoice_service.cancel_invoice(session, invoice)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_read(session, invoice)
