from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DEFAULT_CURRENCY, Currency, VariationStatus
from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class ProjectVariation(Base, TimestampMixin, SoftDeleteMixin):
    """A variation/change order adjusting a project's contract value and/or cost."""

    __tablename__ = "project_variations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    variation_number: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    proposed_value_change: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    approved_value_change: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estimated_cost_change: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    status: Mapped[VariationStatus] = mapped_column(
        SAEnum(VariationStatus, native_enum=False), default=VariationStatus.PROPOSED, nullable=False
    )
    submitted_date: Mapped[date | None] = mapped_column(Date)
    decided_date: Mapped[date | None] = mapped_column(Date)

    def __repr__(self) -> str:
        return f"ProjectVariation(id={self.id!r}, project_id={self.project_id!r}, status={self.status!r})"
