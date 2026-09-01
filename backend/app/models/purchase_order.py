"""Supplier Purchase Order -- the actual ERP procurement document (an
outbound order to a supplier/vendor), NOT the (renamed) client-award
evidence formerly modeled here -- see `app.models.client_award_evidence`
and PO_ARCHITECTURE.md's naming note for that history.

`PurchaseOrderLine.line_total` and `PurchaseOrder.subtotal`/`vat_amount`/
`total` are computed and stored by `purchase_order_service` whenever
lines change -- mirroring the VINCO frontend's `ItemsEditor` (subtotal,
then VAT at one PO-level rate, then total), not per-line VAT. This keeps
the API's totals always consistent with its own lines without a client
having to recompute them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DEFAULT_CURRENCY, Currency, PurchaseOrderStatus
from app.database.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.purchase_request import PurchaseRequest
    from app.models.vendor import Vendor


class PurchaseOrder(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(100), nullable=False)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    purchase_request_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_requests.id"))

    order_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        SAEnum(PurchaseOrderStatus, native_enum=False),
        default=PurchaseOrderStatus.DRAFT,
        nullable=False,
    )
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("15.00"), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    vendor: Mapped["Vendor"] = relationship("Vendor", foreign_keys=[vendor_id])
    project: Mapped["Project"] = relationship("Project", foreign_keys=[project_id])
    purchase_request: Mapped["PurchaseRequest | None"] = relationship(
        "PurchaseRequest", foreign_keys=[purchase_request_id]
    )
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        "PurchaseOrderLine", back_populates="purchase_order", order_by="PurchaseOrderLine.line_no"
    )

    def __repr__(self) -> str:
        return f"PurchaseOrder(id={self.id!r}, po_number={self.po_number!r}, status={self.status!r})"


class PurchaseOrderLine(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(default=1, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("1"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"), nullable=False)

    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="lines")

    def __repr__(self) -> str:
        return f"PurchaseOrderLine(id={self.id!r}, purchase_order_id={self.purchase_order_id!r})"
