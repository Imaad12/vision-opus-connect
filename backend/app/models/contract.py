from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DEFAULT_CURRENCY, ContractStatus, Currency
from app.database.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.quotation import QuotationVersion


class Contract(Base, TimestampMixin, SoftDeleteMixin):
    """The formal agreement created once a `QuotationVersion` is awarded.

    Exactly one `Contract` per `Project` (one-to-one, like
    `Project.winning_quotation_version_id`) -- a project is only ever
    awarded once (see `quotation_service.mark_awarded`), so a second
    contract for the same project would represent a data error, not a
    legitimate re-signing. `value`/`currency` are captured at creation
    from the awarded `Project.contract_value`/`contract_currency` rather
    than referenced live, so this row remains a faithful record of what
    was signed even if a later `ProjectVariation` changes the project's
    effective value. There is deliberately no amendment/versioning model
    here -- a value change after signing is a `ProjectVariation`, exactly
    as it already is for `Project.contract_value` itself.
    """

    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_contracts_project_id"),
        UniqueConstraint("quotation_version_id", name="uq_contracts_quotation_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    quotation_version_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_versions.id"), nullable=False
    )
    contract_number: Mapped[str | None] = mapped_column(String(100))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    status: Mapped[ContractStatus] = mapped_column(
        SAEnum(ContractStatus, native_enum=False), default=ContractStatus.DRAFT, nullable=False
    )
    signed_date: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    project: Mapped["Project"] = relationship("Project", foreign_keys=[project_id])
    quotation_version: Mapped["QuotationVersion"] = relationship(
        "QuotationVersion", foreign_keys=[quotation_version_id]
    )

    def __repr__(self) -> str:
        return f"Contract(id={self.id!r}, project_id={self.project_id!r}, status={self.status!r})"
