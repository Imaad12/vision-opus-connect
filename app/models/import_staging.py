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

from sqlalchemy import Boolean, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    DocumentSourceType,
    ExtractionStatus,
    ImportAuditEventType,
    ImportDocumentKind,
    ImportReviewStatus,
    ClientAwardEvidenceMatchStatus,
    SegmentReviewStatus,
)
from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.boq import BOQ
    from app.models.client import Client
    from app.models.project import Project
    from app.models.client_award_evidence import ClientAwardEvidence
    from app.models.quotation import Quotation, QuotationVersion
    from app.models.vendor import Vendor


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

    # NULL for the original Phase 4 deterministic parsers; "ocr" once OCR
    # Phase 1 extraction produced this document's candidate data. Existing
    # rows are unaffected (NULL), and nothing changes for them -- this
    # column only gates the extra OCR-specific safety checks in
    # `app.services.import_service.confirm_import` and
    # `app.core.ocr_confidence`, never anything for a deterministic import.
    extraction_engine: Mapped[str | None] = mapped_column(String(20))

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
    # Populated only after a PURCHASE_ORDER-kind document is confirmed via
    # `app.services.client_award_evidence_service.confirm_client_award_evidence_import`
    # -- see that module and `ImportedClientAwardEvidenceCandidate` below. NULL
    # for every quotation/BOQ document, unaffected by PO ingestion ever
    # existing.
    resulting_client_award_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("client_award_evidence.id"))

    notes: Mapped[str | None] = mapped_column(Text)

    # The single-candidate relationship kept by the original Phase 4/OCR
    # Phase 1 shape -- one document, one candidate, no segments. Scoped
    # (via the join condition) to rows with no owning segment, so it stays
    # safely 1:1 even for a segmented OCR document, where every candidate
    # instead belongs to one of `segments` below and this relationship
    # simply returns None. Deterministic (non-OCR) documents never gain
    # segments, so this is completely unaffected for them.
    quotation_candidate: Mapped["ImportedQuotationCandidate | None"] = relationship(
        "ImportedQuotationCandidate",
        back_populates="document",
        uselist=False,
        primaryjoin=(
            "and_(ImportedQuotationCandidate.imported_document_id == ImportedDocument.id, "
            "ImportedQuotationCandidate.imported_document_segment_id.is_(None))"
        ),
        viewonly=True,
    )
    boq_line_candidates: Mapped[list["ImportedBoqLineCandidate"]] = relationship(
        "ImportedBoqLineCandidate",
        back_populates="document",
        order_by="ImportedBoqLineCandidate.row_order",
        primaryjoin=(
            "and_(ImportedBoqLineCandidate.imported_document_id == ImportedDocument.id, "
            "ImportedBoqLineCandidate.imported_document_segment_id.is_(None))"
        ),
        viewonly=True,
    )
    #: Sequential-segmentation (see `app.core.import_segmentation`) proposed
    #: page ranges, ordered. Empty for every deterministic (non-OCR)
    #: document and for an OCR document whose extraction never reached
    #: segmentation (e.g. it failed before OCR completed).
    segments: Mapped[list["ImportedDocumentSegment"]] = relationship(
        "ImportedDocumentSegment", back_populates="document", order_by="ImportedDocumentSegment.segment_order"
    )
    audit_log: Mapped[list["ImportAuditLogEntry"]] = relationship(
        "ImportAuditLogEntry", back_populates="document", order_by="ImportAuditLogEntry.occurred_at"
    )
    #: 1:1 -- a PURCHASE_ORDER-kind document has exactly one candidate, no
    #: segmentation (a PO scan is one PO per file; see PO_ARCHITECTURE.md
    #: on this being an explicit, named scope cut for this foundation
    #: round). `None` for every non-PO document.
    client_award_evidence_candidate: Mapped["ImportedClientAwardEvidenceCandidate | None"] = relationship(
        "ImportedClientAwardEvidenceCandidate", back_populates="document", uselist=False
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
    resulting_client_award_evidence: Mapped["ClientAwardEvidence | None"] = relationship(
        "ClientAwardEvidence", foreign_keys=[resulting_client_award_evidence_id]
    )

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
    # No longer unique: a segmented OCR document can own more than one
    # candidate (one per accepted segment). `imported_document_segment_id`
    # below is what's actually unique -- see that column. A deterministic
    # (non-OCR) document is still, by construction, only ever given one
    # candidate row (`run_extraction`'s original code path is unchanged),
    # so this relaxation changes nothing observable for it.
    imported_document_id: Mapped[int] = mapped_column(ForeignKey("imported_documents.id"), nullable=False)
    # NULL for every deterministic (non-OCR) candidate and for an
    # OCR candidate produced before sequential segmentation existed --
    # both keep exactly Phase 4/OCR Phase 1's original one-candidate-per-
    # document shape via `ImportedDocument.quotation_candidate` above. Set
    # (and unique) once a segment has been locked and this candidate was
    # built from that segment's own sliced pages alone -- see
    # `app.services.import_service.lock_segments` and
    # `app.core.import_segmentation.slice_raw_extraction_to_pages`.
    imported_document_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("imported_document_segments.id"), unique=True
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
        "ImportedDocument",
        back_populates="quotation_candidate",
        foreign_keys=[imported_document_id],
        viewonly=True,
    )
    segment: Mapped["ImportedDocumentSegment | None"] = relationship(
        "ImportedDocumentSegment",
        back_populates="quotation_candidate",
        foreign_keys=[imported_document_segment_id],
    )

    def __repr__(self) -> str:
        return f"ImportedQuotationCandidate(imported_document_id={self.imported_document_id!r})"


class ImportedClientAwardEvidenceCandidate(Base, TimestampMixin):
    """Normalized, human-reviewable PO fields extracted from one
    PURCHASE_ORDER-kind document -- see `app.core.po_extraction` and
    `app.services.client_award_evidence_service`. Mirrors
    `ImportedQuotationCandidate`'s shape deliberately (raw_values/
    field_confidence as small JSON dicts, everything nullable).

    `po_reference_number` is the field the business calls "the PO
    reference number" -- per current practice this is the *quotation's own
    reference number* as printed on the PO (not a separate PO-internal
    numbering scheme), and it is the sole key used to find the awarded
    quotation (`match_status`/`matched_quotation_id`, computed
    immediately at extraction time, before any human review). It is never
    fuzzy-matched -- see `ClientAwardEvidenceMatchStatus`.

    `matched_quotation_id` is set only when `match_status == MATCHED`.
    `candidate_quotation_ids` holds the JSON list of every quotation id
    that shared the (normalized) reference when `match_status ==
    AMBIGUOUS`, purely for reviewer diagnostics -- never used to pick one.

    `vendor_name`/`vendor_tax_number` (Supplier/Vendor intelligence
    foundation) are a completely independent identity axis from
    `po_reference_number`'s quotation matching above -- a client PO
    document occasionally names a supplier/subcontractor (e.g. a
    client-nominated subcontractor) that has nothing to do with which
    quotation the PO awards. `vendor_match_status`/`matched_vendor_id`/
    `candidate_vendor_ids` mirror the quotation-matching columns' own
    shape exactly (see `app.services.vendor_matching.match_vendor`) and
    reuse `ClientAwardEvidenceMatchStatus` for the same reason that type is
    reused there: its three values carry no PO-specific meaning. Like the
    quotation match, this is computed at extraction time and never
    fuzzy-matched; unlike the quotation match, a vendor match is never
    required for `confirm_client_award_evidence_import` to succeed -- most real
    client POs will never name a vendor at all, and that must never block
    confirming the PO itself.
    """

    __tablename__ = "imported_client_award_evidence_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    imported_document_id: Mapped[int] = mapped_column(
        ForeignKey("imported_documents.id"), nullable=False, unique=True
    )

    po_reference_number: Mapped[str | None] = mapped_column(String(100))
    po_date: Mapped[date | None] = mapped_column()
    currency: Mapped[str | None] = mapped_column(String(10))
    net_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    gross_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)

    match_status: Mapped[ClientAwardEvidenceMatchStatus] = mapped_column(
        SAEnum(ClientAwardEvidenceMatchStatus, native_enum=False),
        default=ClientAwardEvidenceMatchStatus.UNMATCHED,
        nullable=False,
    )
    matched_quotation_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id"))
    candidate_quotation_ids: Mapped[str | None] = mapped_column(Text)

    vendor_name: Mapped[str | None] = mapped_column(String(255))
    vendor_tax_number: Mapped[str | None] = mapped_column(String(50))
    vendor_match_status: Mapped[ClientAwardEvidenceMatchStatus] = mapped_column(
        SAEnum(ClientAwardEvidenceMatchStatus, native_enum=False),
        default=ClientAwardEvidenceMatchStatus.UNMATCHED,
        nullable=False,
    )
    matched_vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    candidate_vendor_ids: Mapped[str | None] = mapped_column(Text)

    raw_values: Mapped[str | None] = mapped_column(Text)
    field_confidence: Mapped[str | None] = mapped_column(Text)

    document: Mapped["ImportedDocument"] = relationship(
        "ImportedDocument",
        back_populates="client_award_evidence_candidate",
        foreign_keys=[imported_document_id],
    )
    matched_quotation: Mapped["Quotation | None"] = relationship(
        "Quotation", foreign_keys=[matched_quotation_id]
    )
    matched_vendor: Mapped["Vendor | None"] = relationship("Vendor", foreign_keys=[matched_vendor_id])

    def __repr__(self) -> str:
        return (
            f"ImportedClientAwardEvidenceCandidate(imported_document_id={self.imported_document_id!r}, "
            f"match_status={self.match_status!r})"
        )


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
    # NULL for a deterministic (non-OCR) import or a pre-segmentation OCR
    # candidate -- same meaning as the matching column on
    # `ImportedQuotationCandidate` above. Many rows share one segment
    # (unlike the candidate's segment FK, this one is not unique).
    imported_document_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("imported_document_segments.id")
    )
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
        "ImportedDocument",
        back_populates="boq_line_candidates",
        foreign_keys=[imported_document_id],
        viewonly=True,
    )
    segment: Mapped["ImportedDocumentSegment | None"] = relationship(
        "ImportedDocumentSegment",
        back_populates="boq_line_candidates",
        foreign_keys=[imported_document_segment_id],
    )

    def __repr__(self) -> str:
        return f"ImportedBoqLineCandidate(id={self.id!r}, description={self.description!r})"


class ImportedDocumentSegment(Base, TimestampMixin):
    """One proposed (and, once resolved, locked) quotation page range
    within a scanned batch document -- see `app.core.import_segmentation`
    for how it is proposed and IMPORT_ARCHITECTURE.md's sequential
    segmentation section for the full design.

    `review_status` is the single lifecycle axis for both the boundary
    review and the eventual per-segment confirmation (see
    `SegmentReviewStatus`): PROPOSED -> ACCEPTED -> LOCKED -> CONFIRMED |
    REJECTED, or PROPOSED/ACCEPTED -> EXCLUDED_NOT_A_QUOTATION. No
    transition out of PROPOSED happens automatically, regardless of
    `boundary_confidence` -- a human must always act.

    `resulting_*` columns mirror `ImportedDocument`'s own -- populated
    only once *this segment* (not the document as a whole) is confirmed,
    since a segmented document can produce several independent
    `Quotation`/`QuotationVersion` rows, one per confirmed segment.
    """

    __tablename__ = "imported_document_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    imported_document_id: Mapped[int] = mapped_column(ForeignKey("imported_documents.id"), nullable=False)
    segment_order: Mapped[int] = mapped_column(Integer, nullable=False)

    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)

    # `ConfidenceLevel.HIGH`/`ConfidenceLevel.LOW` values -- reusing the
    # existing categorical vocabulary rather than inventing a second one
    # (see `app.core.import_segmentation._classify_boundary`).
    boundary_confidence: Mapped[str | None] = mapped_column(String(20))
    #: Human-readable reasons behind this segment's opening boundary
    #: (newline-joined) -- what a reviewer sees to judge whether to
    #: accept, move, split, merge, or exclude it.
    boundary_signals: Mapped[str | None] = mapped_column(Text)
    #: Segmentation's own best-guess identity for this page range (see
    #: `app.core.import_segmentation.PageSegment`) -- shown to the
    #: reviewer on the boundary screen *before* any candidate exists, so
    #: they have something to judge the proposal against. Purely a
    #: display convenience: never read by `confirm_import` or anything
    #: financial -- the real, reviewable value only ever comes from the
    #: `ImportedQuotationCandidate` built after this segment is locked.
    detected_quotation_number: Mapped[str | None] = mapped_column(String(100))
    detected_quotation_date: Mapped[date | None] = mapped_column()

    review_status: Mapped[SegmentReviewStatus] = mapped_column(
        SAEnum(SegmentReviewStatus, native_enum=False),
        default=SegmentReviewStatus.PROPOSED,
        nullable=False,
    )
    #: True once a reviewer has moved, split, merged, or otherwise changed
    #: this segment's boundary from what segmentation originally proposed
    #: -- an audit signal distinguishing "reviewer agreed with the
    #: proposal" from "reviewer corrected it".
    reviewer_adjusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Populated only after this *segment* (not necessarily the whole
    # document) is confirmed -- see app/services/import_service.py.
    resulting_client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    resulting_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    resulting_quotation_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id"))
    resulting_quotation_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_versions.id")
    )
    resulting_boq_id: Mapped[int | None] = mapped_column(ForeignKey("boqs.id"))

    document: Mapped["ImportedDocument"] = relationship("ImportedDocument", back_populates="segments")
    quotation_candidate: Mapped["ImportedQuotationCandidate | None"] = relationship(
        "ImportedQuotationCandidate", back_populates="segment", uselist=False
    )
    boq_line_candidates: Mapped[list["ImportedBoqLineCandidate"]] = relationship(
        "ImportedBoqLineCandidate", back_populates="segment", order_by="ImportedBoqLineCandidate.row_order"
    )

    resulting_client: Mapped["Client | None"] = relationship("Client", foreign_keys=[resulting_client_id])
    resulting_project: Mapped["Project | None"] = relationship("Project", foreign_keys=[resulting_project_id])
    resulting_quotation: Mapped["Quotation | None"] = relationship(
        "Quotation", foreign_keys=[resulting_quotation_id]
    )
    resulting_quotation_version: Mapped["QuotationVersion | None"] = relationship(
        "QuotationVersion", foreign_keys=[resulting_quotation_version_id]
    )
    resulting_boq: Mapped["BOQ | None"] = relationship("BOQ", foreign_keys=[resulting_boq_id])

    def __repr__(self) -> str:
        return (
            f"ImportedDocumentSegment(id={self.id!r}, pages={self.start_page}-{self.end_page}, "
            f"review_status={self.review_status!r})"
        )


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
