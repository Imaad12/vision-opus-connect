"""Goods/services receiving against a `PurchaseOrder` -- deliberately not
an inventory/warehouse model (no stock locations, no bins, no on-hand
quantities): this is a contracting company ERP, and a `Receipt` only
exists to record "how much of this PO line has actually arrived on
site," which is what `PurchaseOrderLine.received_quantity` and
`PurchaseOrder.status` need to move through PARTIALLY_RECEIVED/RECEIVED.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ReceiptStatus
from app.database.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine


class Receipt(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ReceiptStatus] = mapped_column(
        SAEnum(ReceiptStatus, native_enum=False), default=ReceiptStatus.COMPLETED, nullable=False
    )
    received_by: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", foreign_keys=[purchase_order_id])
    project: Mapped["Project"] = relationship("Project", foreign_keys=[project_id])
    lines: Mapped[list["ReceiptLine"]] = relationship(
        "ReceiptLine", back_populates="receipt", order_by="ReceiptLine.id"
    )

    def __repr__(self) -> str:
        return f"Receipt(id={self.id!r}, purchase_order_id={self.purchase_order_id!r})"


class ReceiptLine(Base, TimestampMixin):
    __tablename__ = "receipt_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), nullable=False)
    purchase_order_line_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_lines.id"), nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)

    receipt: Mapped["Receipt"] = relationship("Receipt", back_populates="lines")
    purchase_order_line: Mapped["PurchaseOrderLine"] = relationship(
        "PurchaseOrderLine", foreign_keys=[purchase_order_line_id]
    )

    def __repr__(self) -> str:
        return f"ReceiptLine(id={self.id!r}, receipt_id={self.receipt_id!r})"
