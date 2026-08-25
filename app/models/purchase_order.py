"""Purchase Order business record (PO ingestion foundation).

A `PurchaseOrder` is the authoritative *evidence* that a `Quotation` was
awarded — see PO_ARCHITECTURE.md. It is created by
`app.services.purchase_order_service.confirm_purchase_order_import` and
ONLY when the PO's extracted reference number matched exactly one
existing `Quotation` (see `app.core.enums.PurchaseOrderMatchStatus`); an
unmatched or ambiguous PO never produces a row here at all — it stays
visible only in the staging layer (`ImportedPurchaseOrderCandidate`),
exactly like an unconfirmed quotation import never produces a
`Quotation` row.

`quotation_id` is therefore always set (never nullable): there is no
"orphan PO" business record with no quotation link in this schema. This
removes an entire class of "PO says project X, quotation says project Y"
inconsistency by construction — a PO never carries its own project/client
link; both are always reached via `purchase_order.quotation.project`.

`po_reference_number` carries a database-wide unique constraint, the same
idempotency mechanism `Quotation.reference_number` already uses: it is
what makes importing the same PO twice (whether the identical file, a
rescanned copy, or a manually re-run confirmation) refuse to create a
second record or a second award, rather than relying on file-hash
deduplication alone (which only catches byte-identical re-imports).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from typing import TYPE_CHECKING

from sqlalchemy import Date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DEFAULT_CURRENCY, Currency
from app.database.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.quotation import Quotation, QuotationVersion


class PurchaseOrder(Base, TimestampMixin, SoftDeleteMixin):
    """A client Purchase Order confirmed as evidence that `quotation` was
    awarded. See module docstring for why `quotation_id` is never null and
    why there is no separate project/client link here."""

    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("po_reference_number", name="uq_purchase_orders_po_reference_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id"), nullable=False)
    # The specific quotation revision that was current at the moment this
    # PO triggered award (or, for a later PO confirmed against an
    # already-awarded quotation, the version that was actually awarded —
    # see `purchase_order_service.confirm_purchase_order_import`). A
    # snapshot, never recomputed later, matching
    # `Project.winning_quotation_version_id`'s own "fixed at award time"
    # convention.
    awarded_quotation_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_versions.id", use_alter=True, name="fk_purchase_orders_awarded_quotation_version")
    )

    po_reference_number: Mapped[str] = mapped_column(String(100), nullable=False)
    po_date: Mapped[date | None] = mapped_column(Date)
    net_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    gross_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    quotation: Mapped["Quotation"] = relationship("Quotation", foreign_keys=[quotation_id])
    awarded_quotation_version: Mapped["QuotationVersion | None"] = relationship(
        "QuotationVersion", foreign_keys=[awarded_quotation_version_id]
    )

    def __repr__(self) -> str:
        return (
            f"PurchaseOrder(id={self.id!r}, po_reference_number={self.po_reference_number!r}, "
            f"quotation_id={self.quotation_id!r})"
        )
