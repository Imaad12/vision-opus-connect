from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DEFAULT_CURRENCY, Currency
from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class BOQ(Base, TimestampMixin, SoftDeleteMixin):
    """A Bill of Quantities, belonging to exactly one QuotationVersion."""

    __tablename__ = "boqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_version_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_versions.id"), nullable=False, unique=True
    )
    title: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"BOQ(id={self.id!r}, quotation_version_id={self.quotation_version_id!r})"


class BOQLineItem(Base, TimestampMixin, SoftDeleteMixin):
    """A single priced line within a BOQ."""

    __tablename__ = "boq_line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    boq_id: Mapped[int] = mapped_column(ForeignKey("boqs.id"), nullable=False)
    line_number: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"))
    unit: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )

    def __repr__(self) -> str:
        return f"BOQLineItem(id={self.id!r}, boq_id={self.boq_id!r}, total={self.total!r})"
