"""Invoice CRUD and status lifecycle.

An `Invoice` is either a client (AR) or vendor (AP) invoice, discriminated
by `direction` -- see `app.models.invoice.Invoice` for why they share one
table. `status` moves `DRAFT -> ISSUED -> (PARTIALLY_PAID) -> PAID`, or to
`CANCELLED`/`DISPUTED` off that path; it is recomputed automatically from
recorded payments (see `recompute_invoice_status`, called by
`payment_service` after every payment is created), never set by amount
comparisons the frontend does itself. `OVERDUE`/`DISPUTED` are the two
statuses this module never sets on its own -- there is no scheduler here
to compare `due_date` to "now", and a dispute is a manual call -- so they
are only ever set by an explicit `update_invoice` call.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DEFAULT_CURRENCY, Currency, InvoiceDirection, InvoiceStatus
from app.core.financial_engine import calculate_amount_due_after_retention, calculate_outstanding_balance
from app.models import Client, Invoice, Payment, Project, Vendor
from app.services.errors import ValidationError

__all__ = [
    "ValidationError",
    "list_invoices",
    "get_invoice",
    "create_invoice",
    "update_invoice",
    "issue_invoice",
    "cancel_invoice",
    "amount_paid",
    "outstanding_balance",
    "recompute_invoice_status",
]


def list_invoices(
    session: Session, *, project_id: int | None = None, direction: InvoiceDirection | None = None
) -> list[Invoice]:
    stmt = select(Invoice).where(Invoice.is_deleted.is_(False))
    if project_id is not None:
        stmt = stmt.where(Invoice.project_id == project_id)
    if direction is not None:
        stmt = stmt.where(Invoice.direction == direction)
    stmt = stmt.order_by(Invoice.id.desc())
    return list(session.execute(stmt).scalars().all())


def get_invoice(session: Session, invoice_id: int) -> Invoice | None:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None or invoice.is_deleted:
        return None
    return invoice


def _validate(
    session: Session,
    *,
    project_id: int,
    direction: InvoiceDirection,
    client_id: int | None,
    vendor_id: int | None,
    tax_amount: Decimal | None,
    retention_amount: Decimal | None,
    amount: Decimal,
) -> None:
    project = session.get(Project, project_id)
    if project is None or project.is_deleted:
        raise ValidationError("Select a valid project.")

    if direction == InvoiceDirection.CLIENT:
        if client_id is None or vendor_id is not None:
            raise ValidationError("A client invoice must have a customer and no vendor.")
        client = session.get(Client, client_id)
        if client is None or client.is_deleted:
            raise ValidationError("Select a valid customer.")
    else:
        if vendor_id is None or client_id is not None:
            raise ValidationError("A vendor invoice must have a vendor and no customer.")
        vendor = session.get(Vendor, vendor_id)
        if vendor is None or vendor.is_deleted:
            raise ValidationError("Select a valid vendor.")

    def _same_sign_within(component: Decimal | None, label: str) -> None:
        if component is None:
            return
        if amount >= 0 and not (0 <= component <= amount):
            raise ValidationError(f"{label} must be between 0 and the invoice amount.")
        if amount < 0 and not (amount <= component <= 0):
            raise ValidationError(f"{label} must be between the invoice amount and 0 for a credit note.")

    _same_sign_within(tax_amount, "Tax amount")
    _same_sign_within(retention_amount, "Retention amount")


def create_invoice(
    session: Session,
    *,
    project_id: int,
    direction: InvoiceDirection,
    client_id: int | None = None,
    vendor_id: int | None = None,
    invoice_number: str | None = None,
    amount: Decimal,
    tax_amount: Decimal | None = None,
    retention_amount: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    issued_date: date | None = None,
    due_date: date | None = None,
    notes: str | None = None,
) -> Invoice:
    _validate(
        session,
        project_id=project_id,
        direction=direction,
        client_id=client_id,
        vendor_id=vendor_id,
        tax_amount=tax_amount,
        retention_amount=retention_amount,
        amount=amount,
    )

    invoice = Invoice(
        project_id=project_id,
        direction=direction,
        client_id=client_id,
        vendor_id=vendor_id,
        invoice_number=(invoice_number or "").strip() or None,
        status=InvoiceStatus.DRAFT,
        amount=amount,
        tax_amount=tax_amount,
        retention_amount=retention_amount,
        currency=currency,
        issued_date=issued_date,
        due_date=due_date,
        notes=(notes or "").strip() or None,
    )
    session.add(invoice)
    session.flush()
    return invoice


def update_invoice(
    session: Session,
    invoice: Invoice,
    *,
    project_id: int,
    direction: InvoiceDirection,
    client_id: int | None = None,
    vendor_id: int | None = None,
    invoice_number: str | None = None,
    amount: Decimal,
    tax_amount: Decimal | None = None,
    retention_amount: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    issued_date: date | None = None,
    due_date: date | None = None,
    status: InvoiceStatus | None = None,
    notes: str | None = None,
) -> Invoice:
    if invoice.status == InvoiceStatus.CANCELLED:
        raise ValidationError("A cancelled invoice cannot be edited.")
    _validate(
        session,
        project_id=project_id,
        direction=direction,
        client_id=client_id,
        vendor_id=vendor_id,
        tax_amount=tax_amount,
        retention_amount=retention_amount,
        amount=amount,
    )

    invoice.project_id = project_id
    invoice.direction = direction
    invoice.client_id = client_id
    invoice.vendor_id = vendor_id
    invoice.invoice_number = (invoice_number or "").strip() or None
    invoice.amount = amount
    invoice.tax_amount = tax_amount
    invoice.retention_amount = retention_amount
    invoice.currency = currency
    invoice.issued_date = issued_date
    invoice.due_date = due_date
    invoice.notes = (notes or "").strip() or None
    if status is not None:
        invoice.status = status
    session.flush()
    return invoice


def issue_invoice(session: Session, invoice: Invoice) -> Invoice:
    if invoice.status != InvoiceStatus.DRAFT:
        raise ValidationError("Only a draft invoice can be issued.")
    invoice.status = InvoiceStatus.ISSUED
    session.flush()
    return invoice


def cancel_invoice(session: Session, invoice: Invoice) -> Invoice:
    if invoice.status == InvoiceStatus.PAID:
        raise ValidationError("A fully paid invoice cannot be cancelled.")
    if amount_paid(session, invoice) > Decimal("0.00"):
        raise ValidationError("An invoice with recorded payments cannot be cancelled.")
    invoice.status = InvoiceStatus.CANCELLED
    session.flush()
    return invoice


def amount_paid(session: Session, invoice: Invoice) -> Decimal:
    stmt = select(Payment).where(Payment.invoice_id == invoice.id, Payment.is_deleted.is_(False))
    return sum((p.amount for p in session.execute(stmt).scalars().all()), Decimal("0.00"))


def amount_paid_bulk(session: Session, invoice_ids: list[int]) -> dict[int, Decimal]:
    """Same figure as `amount_paid`, for many invoices in one query instead
    of one query per invoice -- used by the invoice list endpoint, where
    calling `amount_paid` per row was a confirmed N+1 (one `SELECT ...
    FROM payments` per invoice in the response)."""
    if not invoice_ids:
        return {}
    stmt = select(Payment.invoice_id, Payment.amount).where(
        Payment.invoice_id.in_(invoice_ids), Payment.is_deleted.is_(False)
    )
    totals: dict[int, Decimal] = dict.fromkeys(invoice_ids, Decimal("0.00"))
    for invoice_id, amount in session.execute(stmt).all():
        totals[invoice_id] = totals[invoice_id] + amount
    return totals


def outstanding_balance(session: Session, invoice: Invoice) -> Decimal | None:
    due = calculate_amount_due_after_retention(invoice.amount, invoice.retention_amount)
    return calculate_outstanding_balance(due, amount_paid(session, invoice))


def recompute_invoice_status(session: Session, invoice: Invoice) -> Invoice:
    """Re-derive `status` from recorded payments. A no-op for
    `DRAFT`/`CANCELLED`/`DISPUTED` invoices -- those are only ever changed
    by an explicit `update_invoice` call, never by a payment being
    recorded against them."""
    if invoice.status in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED, InvoiceStatus.DISPUTED):
        return invoice

    due = calculate_amount_due_after_retention(invoice.amount, invoice.retention_amount)
    paid = amount_paid(session, invoice)
    if paid <= Decimal("0.00"):
        invoice.status = InvoiceStatus.ISSUED
    elif due is not None and paid >= due:
        invoice.status = InvoiceStatus.PAID
    else:
        invoice.status = InvoiceStatus.PARTIALLY_PAID
    session.flush()
    return invoice
