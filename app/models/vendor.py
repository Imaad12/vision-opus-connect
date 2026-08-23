from __future__ import annotations

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import VendorType
from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class Vendor(Base, TimestampMixin, SoftDeleteMixin):
    """A supplier or subcontractor.

    Suppliers and subcontractors are modeled as one table with a
    `vendor_type` discriminator rather than two tables, since they share
    the same shape and are used interchangeably by ActualCost/Invoice. See
    DATABASE_SCHEMA.md section 3.9 for the rationale.
    """

    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_type: Mapped[VendorType] = mapped_column(
        SAEnum(VendorType, native_enum=False), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    payment_terms: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Vendor(id={self.id!r}, name={self.name!r}, type={self.vendor_type!r})"
