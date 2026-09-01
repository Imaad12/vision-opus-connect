from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, false
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DEFAULT_CURRENCY, Currency, InvoiceDirection, InvoiceStatus, PaymentMethod
from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class Invoice(Base, TimestampMixin, SoftDeleteMixin):
    """An invoice, either issued to a client (CLIENT/AR) or received from a
    vendor (VENDOR/AP). Exactly one of client_id/vendor_id is set, matching
    `direction`.

    `amount` is the TOTAL face value of the invoice (inclusive of tax) —
    what the invoice document itself states is owed. `tax_amount` and
    `retention_amount` are components *within* that total, not additions to
    it: `amount - tax_amount` is the tax-exclusive (net) revenue/cost this
    invoice represents, and `amount - retention_amount` is what is
    currently payable/collectible on it (the rest being held back until
    release). Both default to untracked (`None`), which the financial
    engine treats as zero — see `app/core/financial_engine.py`.

    A negative `amount` represents a credit note (a reversal of previously
    invoiced value); `tax_amount`/`retention_amount` on a credit note must
    carry the same sign, enforced by the CHECK constraints below.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "(direction = 'CLIENT' AND client_id IS NOT NULL AND vendor_id IS NULL) OR "
            "(direction = 'VENDOR' AND vendor_id IS NOT NULL AND client_id IS NULL)",
            name="ck_invoices_direction_party",
        ),
        CheckConstraint(
            "tax_amount IS NULL OR "
            "(amount >= 0 AND tax_amount >= 0 AND tax_amount <= amount) OR "
            "(amount < 0 AND tax_amount <= 0 AND tax_amount >= amount)",
            name="ck_invoices_tax_amount_range",
        ),
        CheckConstraint(
            "retention_amount IS NULL OR "
            "(amount >= 0 AND retention_amount >= 0 AND retention_amount <= amount) OR "
            "(amount < 0 AND retention_amount <= 0 AND retention_amount >= amount)",
            name="ck_invoices_retention_amount_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    direction: Mapped[InvoiceDirection] = mapped_column(
        SAEnum(InvoiceDirection, native_enum=False), nullable=False
    )
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(InvoiceStatus, native_enum=False), default=InvoiceStatus.DRAFT, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    retention_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    issued_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Invoice(id={self.id!r}, direction={self.direction!r}, amount={self.amount!r})"


class Payment(Base, TimestampMixin, SoftDeleteMixin):
    """A payment recorded against an invoice.

    `is_retention_release` marks a payment that releases previously
    withheld retention (see `Invoice.retention_amount`), as opposed to an
    ordinary progress payment — this is what lets "retention outstanding"
    be computed as withheld-to-date minus released-to-date rather than
    only ever growing. It defaults to False (an ordinary payment).
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    paid_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[PaymentMethod | None] = mapped_column(SAEnum(PaymentMethod, native_enum=False))
    reference: Mapped[str | None] = mapped_column(String(100))
    is_retention_release: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Payment(id={self.id!r}, invoice_id={self.invoice_id!r}, amount={self.amount!r})"
