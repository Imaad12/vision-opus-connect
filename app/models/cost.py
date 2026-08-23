from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, true
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DEFAULT_CURRENCY, CostPaymentStatus, Currency
from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class EstimatedCost(Base, TimestampMixin, SoftDeleteMixin):
    """A line item making up the estimated cost of a project at tender stage.

    `amount` is the line's total (what the brief calls "total"): when
    `quantity` and `unit_rate` are both provided, `amount` should equal
    `quantity * unit_rate` (kept in sync by the service layer via
    `app.core.financial_engine.calculate_line_total`, not a DB trigger,
    matching the convention already used by `BOQLineItem.total`).
    `quantity`/`unit`/`unit_rate` are optional because a cost can also be
    entered directly as a lump sum.
    """

    __tablename__ = "estimated_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    quotation_version_id: Mapped[int | None] = mapped_column(ForeignKey("quotation_versions.id"))
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("cost_categories.id"), nullable=False)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"))
    description: Mapped[str | None] = mapped_column(String(500))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"EstimatedCost(id={self.id!r}, project_id={self.project_id!r}, amount={self.amount!r})"


class ActualCost(Base, TimestampMixin, SoftDeleteMixin):
    """A cost actually incurred during project execution, recognized on an
    accrual basis (i.e. independent of whether the linked vendor invoice,
    if any, has itself been paid — see `payment_status` below and
    DATABASE_SCHEMA.md).

    `amount` is the GROSS amount incurred (inclusive of tax), consistent
    with `Invoice.amount`. `tax_amount` is the VAT/tax component within it.
    By default (`is_tax_recoverable=True`) VAT is excluded from the
    project's recognized cost — see
    `app.core.financial_engine.calculate_recognized_cost` — since it is
    reclaimable and not a real cost to the business. Setting
    `is_tax_recoverable=False` (e.g. blocked input VAT, or a non-VAT-
    registered supplier situation) means the tax is genuinely unrecoverable
    and the full gross amount counts as project cost.
    """

    __tablename__ = "actual_costs"
    __table_args__ = (
        CheckConstraint(
            "tax_amount IS NULL OR "
            "(amount >= 0 AND tax_amount >= 0 AND tax_amount <= amount) OR "
            "(amount < 0 AND tax_amount <= 0 AND tax_amount >= amount)",
            name="ck_actual_costs_tax_amount_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("cost_categories.id"), nullable=False)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    reference_number: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_tax_recoverable: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    payment_status: Mapped[CostPaymentStatus] = mapped_column(
        SAEnum(CostPaymentStatus, native_enum=False),
        default=CostPaymentStatus.UNPAID,
        server_default=CostPaymentStatus.UNPAID.value,
        nullable=False,
    )
    incurred_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"ActualCost(id={self.id!r}, project_id={self.project_id!r}, amount={self.amount!r})"
