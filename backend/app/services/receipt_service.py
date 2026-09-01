"""Receiving against a Purchase Order.

Creating a `Receipt` is the only way `PurchaseOrderLine.received_quantity`
ever changes, and the only way a `PurchaseOrder` ever moves to
`PARTIALLY_RECEIVED`/`RECEIVED` -- `purchase_order_service` never sets
those itself. A receipt is a completed record of what physically
arrived; there is no draft/edit state (see `ReceiptStatus`), matching
"do not overbuild inventory functionality" -- correcting a mistaken
receipt is a `cancel_receipt`, not an edit.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PurchaseOrderStatus, ReceiptStatus
from app.models import PurchaseOrder, PurchaseOrderLine, Receipt, ReceiptLine
from app.services.errors import ValidationError

__all__ = [
    "ValidationError",
    "list_receipts_for_purchase_order",
    "get_receipt",
    "create_receipt",
    "cancel_receipt",
]


def list_receipts_for_purchase_order(session: Session, purchase_order_id: int) -> list[Receipt]:
    stmt = (
        select(Receipt)
        .where(Receipt.purchase_order_id == purchase_order_id, Receipt.is_deleted.is_(False))
        .order_by(Receipt.id.desc())
    )
    return list(session.execute(stmt).scalars().all())


def get_receipt(session: Session, receipt_id: int) -> Receipt | None:
    receipt = session.get(Receipt, receipt_id)
    if receipt is None or receipt.is_deleted:
        return None
    return receipt


def _refresh_purchase_order_status(po: PurchaseOrder) -> None:
    if not po.lines:
        return
    if all(line.received_quantity >= line.quantity for line in po.lines):
        po.status = PurchaseOrderStatus.RECEIVED
    elif any(line.received_quantity > 0 for line in po.lines):
        po.status = PurchaseOrderStatus.PARTIALLY_RECEIVED


def create_receipt(
    session: Session,
    po: PurchaseOrder,
    *,
    receipt_date: date,
    lines: list[dict],
    received_by: str | None = None,
    notes: str | None = None,
) -> Receipt:
    if po.status not in (PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.PARTIALLY_RECEIVED):
        raise ValidationError("Only an approved purchase order can receive goods.")
    if not lines:
        raise ValidationError("Record at least one received line.")

    po_lines_by_id = {line.id: line for line in po.lines}

    receipt = Receipt(
        purchase_order_id=po.id,
        project_id=po.project_id,
        receipt_date=receipt_date,
        status=ReceiptStatus.COMPLETED,
        received_by=(received_by or "").strip() or None,
        notes=(notes or "").strip() or None,
    )
    session.add(receipt)
    session.flush()

    for raw in lines:
        po_line_id = raw.get("purchase_order_line_id")
        po_line = po_lines_by_id.get(po_line_id)
        if po_line is None:
            raise ValidationError("A receipt line must reference a line on this purchase order.")
        quantity_received = Decimal(str(raw.get("quantity_received", 0)))
        if quantity_received <= 0:
            raise ValidationError("Received quantity must be positive.")
        remaining = po_line.quantity - po_line.received_quantity
        if quantity_received > remaining:
            raise ValidationError(
                f"Cannot receive {quantity_received} of '{po_line.description}' -- only "
                f"{remaining} remains outstanding."
            )
        session.add(
            ReceiptLine(
                receipt_id=receipt.id,
                purchase_order_line_id=po_line.id,
                quantity_received=quantity_received,
            )
        )
        po_line.received_quantity += quantity_received

    _refresh_purchase_order_status(po)
    session.flush()
    return receipt


def cancel_receipt(session: Session, receipt: Receipt) -> Receipt:
    if receipt.status != ReceiptStatus.COMPLETED:
        raise ValidationError("This receipt is already cancelled.")
    for line in receipt.lines:
        po_line = session.get(PurchaseOrderLine, line.purchase_order_line_id)
        if po_line is not None:
            po_line.received_quantity -= line.quantity_received
    receipt.status = ReceiptStatus.CANCELLED
    _refresh_purchase_order_status(receipt.purchase_order)
    if not any(line.received_quantity > 0 for line in receipt.purchase_order.lines):
        receipt.purchase_order.status = PurchaseOrderStatus.APPROVED
    session.flush()
    return receipt
