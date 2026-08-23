from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DEFAULT_CURRENCY, Currency
from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class EstimatedCost(Base, TimestampMixin, SoftDeleteMixin):
    """A line item making up the estimated cost of a project at tender stage."""

    __tablename__ = "estimated_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    quotation_version_id: Mapped[int | None] = mapped_column(ForeignKey("quotation_versions.id"))
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("cost_categories.id"), nullable=False)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"))
    description: Mapped[str | None] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )

    def __repr__(self) -> str:
        return f"EstimatedCost(id={self.id!r}, project_id={self.project_id!r}, amount={self.amount!r})"


class ActualCost(Base, TimestampMixin, SoftDeleteMixin):
    """A cost actually incurred during project execution."""

    __tablename__ = "actual_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("cost_categories.id"), nullable=False)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    description: Mapped[str | None] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    incurred_date: Mapped[date | None] = mapped_column(Date)

    def __repr__(self) -> str:
        return f"ActualCost(id={self.id!r}, project_id={self.project_id!r}, amount={self.amount!r})"
