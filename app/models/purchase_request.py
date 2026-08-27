from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DEFAULT_CURRENCY, Currency, PurchaseRequestStatus
from app.database.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.vendor import Vendor


class PurchaseRequest(Base, TimestampMixin, SoftDeleteMixin):
    """An internal request to buy something for a project, raised before a
    `PurchaseOrder` exists. Deliberately lightweight: `items_description`
    is free text (what's needed), not a structured line-item table -- the
    precise, priced breakdown belongs on the `PurchaseOrder` once this
    request is approved and converted, not duplicated here."""

    __tablename__ = "purchase_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    requested_by: Mapped[str | None] = mapped_column(String(255))
    items_description: Mapped[str] = mapped_column(Text, nullable=False)
    requested_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    status: Mapped[PurchaseRequestStatus] = mapped_column(
        SAEnum(PurchaseRequestStatus, native_enum=False),
        default=PurchaseRequestStatus.DRAFT,
        nullable=False,
    )
    requested_date: Mapped[date | None] = mapped_column(Date)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    project: Mapped["Project"] = relationship("Project", foreign_keys=[project_id])
    vendor: Mapped["Vendor | None"] = relationship("Vendor", foreign_keys=[vendor_id])

    def __repr__(self) -> str:
        return f"PurchaseRequest(id={self.id!r}, project_id={self.project_id!r}, status={self.status!r})"
