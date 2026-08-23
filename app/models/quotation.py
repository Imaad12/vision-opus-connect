from __future__ import annotations

from datetime import date
from decimal import Decimal

from typing import TYPE_CHECKING

from sqlalchemy import Date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DEFAULT_CURRENCY, Currency, QuotationStatus
from app.database.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.boq import BOQ
    from app.models.project import Project


class Quotation(Base, TimestampMixin, SoftDeleteMixin):
    """A tender opportunity on a project. A project may have more than one
    (e.g. if it is re-tendered)."""

    __tablename__ = "quotations"
    __table_args__ = (UniqueConstraint("reference_number", name="uq_quotations_reference_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(255))

    project: Mapped["Project"] = relationship("Project", foreign_keys=[project_id])

    def __repr__(self) -> str:
        return f"Quotation(id={self.id!r}, project_id={self.project_id!r})"


class QuotationVersion(Base, TimestampMixin, SoftDeleteMixin):
    """A specific revision of a Quotation. Revisions are preserved, never
    overwritten, so estimating history is auditable."""

    __tablename__ = "quotation_versions"
    __table_args__ = (
        UniqueConstraint("quotation_id", "version_number", name="uq_quotation_version_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[QuotationStatus] = mapped_column(
        SAEnum(QuotationStatus, native_enum=False),
        default=QuotationStatus.DRAFT,
        nullable=False,
    )
    quoted_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    issued_date: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    quotation: Mapped["Quotation"] = relationship("Quotation", foreign_keys=[quotation_id])
    boq: Mapped["BOQ | None"] = relationship(
        "BOQ", foreign_keys="BOQ.quotation_version_id", uselist=False, viewonly=True
    )

    def __repr__(self) -> str:
        return (
            f"QuotationVersion(id={self.id!r}, quotation_id={self.quotation_id!r}, "
            f"version_number={self.version_number!r}, status={self.status!r})"
        )
