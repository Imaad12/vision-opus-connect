from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DEFAULT_CURRENCY, Currency, LeadSource, LeadStatus
from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class Lead(Base, TimestampMixin, SoftDeleteMixin):
    """A pre-project sales opportunity.

    Deliberately independent of `Project` (whose own `status` also starts
    at LEAD/TENDERING): a `Lead` may never become a project at all, so this
    is a separate pipeline that precedes the decision to formally track a
    project, not a duplicate of `Project.status`. When a lead is won,
    `converted_project_id` optionally links to the `Project` created for
    it -- set manually by the caller, never automatically.

    `owner_id` is a Supabase auth user id (opaque string, not a FK) --
    the backend has no user directory of its own; see PurchaseRequest.
    requested_by for the same convention.
    """

    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 100)",
            name="ck_leads_probability_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    source: Mapped[LeadSource | None] = mapped_column(SAEnum(LeadSource, native_enum=False))
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus, native_enum=False), default=LeadStatus.NEW, server_default=LeadStatus.NEW.value, nullable=False
    )
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    probability: Mapped[int | None] = mapped_column(Integer)
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    converted_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))

    def __repr__(self) -> str:
        return f"Lead(id={self.id!r}, title={self.title!r}, status={self.status!r})"
