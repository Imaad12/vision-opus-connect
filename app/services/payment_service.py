"""Payment CRUD -- a receipt or disbursement recorded against an invoice.

Creating, editing, or voiding a payment always recomputes the parent
invoice's status via `invoice_service.recompute_invoice_status` -- the
invoice's `status` is never trusted from client input once payments
exist against it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DEFAULT_CURRENCY, Currency, InvoiceStatus, PaymentMethod
from app.models import Invoice, Payment
from app.services import invoice_service
from app.services.errors import ValidationError

__all__ = ["ValidationError", "list_payments", "get_payment", "create_payment", "void_payment"]


def list_payments(session: Session, *, invoice_id: int | None = None) -> list[Payment]:
    stmt = select(Payment).where(Payment.is_deleted.is_(False))
    if invoice_id is not None:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    stmt = stmt.order_by(Payment.paid_date.desc(), Payment.id.desc())
    return list(session.execute(stmt).scalars().all())


def get_payment(session: Session, payment_id: int) -> Payment | None:
    payment = session.get(Payment, payment_id)
    if payment is None or payment.is_deleted:
        return None
    return payment


def create_payment(
    session: Session,
    *,
    invoice_id: int,
    amount: Decimal,
    paid_date: date,
    currency: Currency = DEFAULT_CURRENCY,
    method: PaymentMethod | None = None,
    reference: str | None = None,
    is_retention_release: bool = False,
    notes: str | None = None,
) -> Payment:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None or invoice.is_deleted:
        raise ValidationError("Select a valid invoice.")
    if invoice.status in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED):
        raise ValidationError("Cannot record a payment against a draft or cancelled invoice.")
    if amount == 0:
        raise ValidationError("Payment amount cannot be zero.")

    payment = Payment(
        invoice_id=invoice_id,
        amount=amount,
        currency=currency,
        paid_date=paid_date,
        method=method,
        reference=(reference or "").strip() or None,
        is_retention_release=is_retention_release,
        notes=(notes or "").strip() or None,
    )
    session.add(payment)
    session.flush()
    invoice_service.recompute_invoice_status(session, invoice)
    return payment


def void_payment(session: Session, payment: Payment) -> Payment:
    invoice = session.get(Invoice, payment.invoice_id)
    payment.is_deleted = True
    session.flush()
    if invoice is not None:
        invoice_service.recompute_invoice_status(session, invoice)
    return payment
