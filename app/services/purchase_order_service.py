"""Supplier Purchase Order CRUD, line items, and approval lifecycle.

`DRAFT -> PENDING_APPROVAL -> APPROVED -> (PARTIALLY_RECEIVED|RECEIVED)`,
or `CANCELLED`/`REJECTED` off that path. Receiving is driven entirely by
`receipt_service` -- this module never sets `PARTIALLY_RECEIVED`/
`RECEIVED` itself.

Totals (`subtotal`/`vat_amount`/`total`) are always recomputed from the
current lines whenever lines are replaced -- see `set_purchase_order_lines`
-- mirroring the VINCO frontend's own `ItemsEditor` (one VAT rate applied
to the line subtotal), so the API is never the source of a stale total.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import DEFAULT_CURRENCY, Currency, PurchaseOrderStatus
from app.models import Project, PurchaseOrder, PurchaseOrderLine, PurchaseRequest, Vendor
from app.services.errors import ValidationError

__all__ = [
    "ValidationError",
    "list_purchase_orders",
    "get_purchase_order",
    "create_purchase_order",
    "set_purchase_order_lines",
    "submit_purchase_order",
    "approve_purchase_order",
    "reject_purchase_order",
    "cancel_purchase_order",
]

TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def list_purchase_orders(session: Session, *, project_id: int | None = None) -> list[PurchaseOrder]:
    stmt = select(PurchaseOrder).where(PurchaseOrder.is_deleted.is_(False))
    if project_id is not None:
        stmt = stmt.where(PurchaseOrder.project_id == project_id)
    stmt = stmt.order_by(PurchaseOrder.id.desc())
    return list(session.execute(stmt).scalars().all())


def get_purchase_order(session: Session, purchase_order_id: int) -> PurchaseOrder | None:
    po = session.get(PurchaseOrder, purchase_order_id)
    if po is None or po.is_deleted:
        return None
    return po


def create_purchase_order(
    session: Session,
    *,
    po_number: str,
    vendor_id: int,
    project_id: int,
    purchase_request_id: int | None = None,
    order_date: date | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    vat_rate: Decimal = Decimal("15.00"),
    notes: str | None = None,
) -> PurchaseOrder:
    po_number = (po_number or "").strip()
    if not po_number:
        raise ValidationError("PO number is required.")

    vendor = session.get(Vendor, vendor_id)
    if vendor is None or vendor.is_deleted:
        raise ValidationError("Select a valid vendor.")

    project = session.get(Project, project_id)
    if project is None or project.is_deleted:
        raise ValidationError("Select a valid project.")

    if purchase_request_id is not None:
        request = session.get(PurchaseRequest, purchase_request_id)
        if request is None or request.is_deleted:
            raise ValidationError("Select a valid purchase request.")

    po = PurchaseOrder(
        po_number=po_number,
        vendor_id=vendor_id,
        project_id=project_id,
        purchase_request_id=purchase_request_id,
        order_date=order_date,
        currency=currency,
        vat_rate=vat_rate,
        subtotal=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        total=Decimal("0.00"),
        notes=(notes or "").strip() or None,
    )
    session.add(po)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ValidationError(f"PO number '{po_number}' is already in use.") from exc
    return po


def set_purchase_order_lines(
    session: Session,
    po: PurchaseOrder,
    lines: list[dict],
) -> PurchaseOrder:
    """Replace every line on `po` with `lines` and recompute totals --
    the same replace-all-on-save shape the frontend's `ItemsEditor`
    already uses for quotations/POs, so wiring it here needs no new UI
    pattern."""
    if po.status not in (PurchaseOrderStatus.DRAFT,):
        raise ValidationError("Only a draft purchase order's lines can be edited.")

    for existing in list(po.lines):
        po.lines.remove(existing)
        session.delete(existing)
    session.flush()

    subtotal = Decimal("0.00")
    for i, raw in enumerate(lines, start=1):
        description = (raw.get("description") or "").strip()
        if not description:
            raise ValidationError("Every line needs a description.")
        quantity = Decimal(str(raw.get("quantity", 1)))
        unit_price = Decimal(str(raw.get("unit_price", 0)))
        if quantity <= 0:
            raise ValidationError("Line quantity must be positive.")
        if unit_price < 0:
            raise ValidationError("Line unit price cannot be negative.")
        line_total = _round(quantity * unit_price)
        subtotal += line_total
        # Appended to the relationship (not `session.add`) so `po.lines`
        # reflects the new rows immediately -- callers (and the API
        # response) read `po.lines` right after this returns, in the same
        # session, before any expire/refresh would otherwise pick it up.
        po.lines.append(
            PurchaseOrderLine(
                line_no=i,
                description=description,
                unit=(raw.get("unit") or "").strip() or None,
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

    po.subtotal = _round(subtotal)
    po.vat_amount = _round(po.subtotal * po.vat_rate / Decimal("100"))
    po.total = _round(po.subtotal + po.vat_amount)
    session.flush()
    return po


def submit_purchase_order(session: Session, po: PurchaseOrder) -> PurchaseOrder:
    if po.status != PurchaseOrderStatus.DRAFT:
        raise ValidationError("Only a draft purchase order can be submitted.")
    if not po.lines:
        raise ValidationError("Add at least one line before submitting.")
    po.status = PurchaseOrderStatus.PENDING_APPROVAL
    session.flush()
    return po


def approve_purchase_order(session: Session, po: PurchaseOrder) -> PurchaseOrder:
    if po.status != PurchaseOrderStatus.PENDING_APPROVAL:
        raise ValidationError("Only a purchase order pending approval can be approved.")
    po.status = PurchaseOrderStatus.APPROVED
    session.flush()
    return po


def reject_purchase_order(session: Session, po: PurchaseOrder) -> PurchaseOrder:
    if po.status != PurchaseOrderStatus.PENDING_APPROVAL:
        raise ValidationError("Only a purchase order pending approval can be rejected.")
    po.status = PurchaseOrderStatus.REJECTED
    session.flush()
    return po


def cancel_purchase_order(session: Session, po: PurchaseOrder) -> PurchaseOrder:
    if po.status not in (
        PurchaseOrderStatus.DRAFT,
        PurchaseOrderStatus.PENDING_APPROVAL,
        PurchaseOrderStatus.APPROVED,
    ):
        raise ValidationError("This purchase order can no longer be cancelled.")
    po.status = PurchaseOrderStatus.CANCELLED
    session.flush()
    return po
