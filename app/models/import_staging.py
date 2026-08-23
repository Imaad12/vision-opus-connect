"""Import staging models (Phase 4).

These tables are the "staging area" described in IMPORT_ARCHITECTURE.md:
nothing here is a business record. An `ImportedDocument` and its candidate
rows exist purely so a human can review what a deterministic parser found
before any of it is allowed to become a `Quotation`, `BOQ`, `Project`, or
`Client` row. No column on any model in this file is ever read by
`app.core.financial_engine` or counted toward profit/margin/cost.

Layering, per document (see IMPORT_ARCHITECTURE.md §2):

    ImportedDocument            -- one row per imported source file
        .raw_extracted_data     -- RAW layer: exactly what the parser found
        -> ImportedQuotationCandidate   -- NORMALIZED layer, quotation-shaped
        -> ImportedBoqLineCandidate[]   -- NORMALIZED layer, BOQ-row-shaped
        -> ImportAuditLogEntry[]        -- lifecycle + per-field edit history

`ImportedDocument.created_at` (from `TimestampMixin`) doubles as "import
date" — a staging record is created at the moment a file is imported, so a
separate column would only ever duplicate it.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    DocumentSourceType,
    ExtractionStatus,
    ImportAuditEventType,
    ImportDocumentKind,
    ImportReviewStatus,
)
from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.boq import BOQ
    from app.models.client import Client
    from app.models.project import Project
    from app.models.quotation import Quotation, QuotationVersion


class ImportedDocument(Base, TimestampMixin):
    """A source file the user imported, and everything known about it so
    far. Never modifies, moves, or copies the original file — `original_path`
    is only a reference (see IMPORT_ARCHITECTURE.md §3 on why paths are not
    assumed to be permanent)."""

    __tablename__ = "imported_documents"

    id: Mapped[int] = mapped_column(primary_key=True)

    source_type: Mapped[DocumentSourceType] = mapped_column(
        SAEnum(DocumentSourceType, native_enum=False),
        default=DocumentSourceType.LOCAL,
        nullable=False,
    )
    document_kind: Mapped[ImportDocumentKind] = mapped_column(
        SAEnum(ImportDocumentKind, native_enum=False),
        default=ImportDocumentKind.UNKNOWN,
        nullable=False,
    )

    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        SAEnum(ExtractionStatus, native_enum=False),
        default=ExtractionStatus.PENDING,
        nullable=False,
    )
    extraction_error: Mapped[str | None] = mapped_column(Text)
    raw_extracted_data: Mapped[str | None] = mapped_column(Text)

    review_status: Mapped[ImportReviewStatus] = mapped_column(
        SAEnum(ImportReviewStatus, native_enum=False),
        default=ImportReviewStatus.NEEDS_REVIEW,
        nullable=False,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Populated only after CONFIRM IMPORT — see app/services/import_service.py.
    resulting_client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    resulting_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    resulting_quotation_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id"))
    resulting_quotation_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_versions.id")
    )
    resulting_boq_id: Mapped[int | None] = mapped_column(ForeignKey("boqs.id"))

    notes: Mapped[str | None] = mapped_column(Text)

    quotation_candidate: Mapped["ImportedQuotationCandidate | None"] = relationship(
        "ImportedQuotationCandidate", back_populates="document", uselist=False
    )
    boq_line_candidates: Mapped[list["ImportedBoqLineCandidate"]] = relationship(
        "ImportedBoqLineCandidate", back_populates="document", order_by="ImportedBoqLineCandidate.row_order"
    )
    audit_log: Mapped[list["ImportAuditLogEntry"]] = relationship(
        "ImportAuditLogEntry", back_populates="document", order_by="ImportAuditLogEntry.occurred_at"
    )

    resulting_client: Mapped["Client | None"] = relationship(
        "Client", foreign_keys=[resulting_client_id]
    )
    resulting_project: Mapped["Project | None"] = relationship(
        "Project", foreign_keys=[resulting_project_id]
    )
    resulting_quotation: Mapped["Quotation | None"] = relationship(
        "Quotation", foreign_keys=[resulting_quotation_id]
    )
    resulting_quotation_version: Mapped["QuotationVersion | None"] = relationship(
        "QuotationVersion", foreign_keys=[resulting_quotation_version_id]
    )
    resulting_boq: Mapped["BOQ | None"] = relationship("BOQ", foreign_keys=[resulting_boq_id])

    def __repr__(self) -> str:
        return (
            f"ImportedDocument(id={self.id!r}, filename={self.filename!r}, "
            f"extraction_status={self.extraction_status!r}, review_status={self.review_status!r})"
        )


class ImportedQuotationCandidate(Base, TimestampMixin):
    """Normalized, human-reviewable quotation fields extracted from one
    document. Every field is nullable — a partially-recognized document is
    still useful for a human to complete, never silently dropped.

    `raw_values` and `field_confidence` are small JSON dicts keyed by this
    model's field names (e.g. `{"net_value": "AED 1,250,000.00"}` /
    `{"net_value": "HIGH"}`) rather than one column per field per concept —
    see IMPORT_ARCHITECTURE.md §6 for why.
    """

    __tablename__ = "imported_quotation_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    imported_document_id: Mapped[int] = mapped_column(
        ForeignKey("imported_documents.id"), nullable=False, unique=True
    )

    quotation_number: Mapped[str | None] = mapped_column(String(100))
    quotation_date: Mapped[date | None] = mapped_column()
    client_name: Mapped[str | None] = mapped_column(String(255))
    project_name: Mapped[str | None] = mapped_column(String(255))
    project_number: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(String(10))
    net_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    gross_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    valid_until: Mapped[date | None] = mapped_column()
    payment_terms: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    raw_values: Mapped[str | None] = mapped_column(Text)
    field_confidence: Mapped[str | None] = mapped_column(Text)

    document: Mapped["ImportedDocument"] = relationship(
        "ImportedDocument", back_populates="quotation_candidate", foreign_keys=[imported_document_id]
    )

    def __repr__(self) -> str:
        return f"ImportedQuotationCandidate(imported_document_id={self.imported_document_id!r})"


class ImportedBoqLineCandidate(Base, TimestampMixin):
    """One candidate BOQ row extracted from a document. `extracted_amount`
    (what the source actually said) and `calculated_amount`
    (quantity * unit_rate, via the same `calculate_line_total` the rest of
    the app uses) are kept side by side deliberately — see
    IMPORT_ARCHITECTURE.md §7. Neither is ever silently overwritten by the
    other; `amount_flagged` marks a material mismatch for review.
    """

    __tablename__ = "imported_boq_line_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    imported_document_id: Mapped[int] = mapped_column(ForeignKey("imported_documents.id"), nullable=False)
    row_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    group_label: Mapped[str | None] = mapped_column(String(255))
    item_number: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    category_label: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    extracted_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    calculated_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    amount_flagged: Mapped[bool] = mapped_column(default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    document: Mapped["ImportedDocument"] = relationship(
        "ImportedDocument", back_populates="boq_line_candidates", foreign_keys=[imported_document_id]
    )

    def __repr__(self) -> str:
        return f"ImportedBoqLineCandidate(id={self.id!r}, description={self.description!r})"


class ImportAuditLogEntry(Base):
    """Immutable lifecycle/edit trail for one `ImportedDocument`.

    `old_value`/`new_value` are plain strings (already-formatted, not
    `Decimal`/`date`) since this is a historical text log, not data other
    code reads back — the reviewable, editable value always lives on the
    candidate row itself.
    """

    __tablename__ = "import_audit_log_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    imported_document_id: Mapped[int] = mapped_column(ForeignKey("imported_documents.id"), nullable=False)
    event_type: Mapped[ImportAuditEventType] = mapped_column(
        SAEnum(ImportAuditEventType, native_enum=False), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    document: Mapped["ImportedDocument"] = relationship(
        "ImportedDocument", back_populates="audit_log", foreign_keys=[imported_document_id]
    )

    def __repr__(self) -> str:
        return (
            f"ImportAuditLogEntry(imported_document_id={self.imported_document_id!r}, "
            f"event_type={self.event_type!r})"
        )
