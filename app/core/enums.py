"""Shared enumerations.

These carry no dependency on SQLAlchemy, Qt, or pandas so they can be used
from `core`, `models`, `services`, and `ui` alike without pulling in any
particular framework.
"""

from __future__ import annotations

from enum import StrEnum


class Currency(StrEnum):
    """ISO-4217 currency codes in common use by the business.

    This is not an exhaustive ISO-4217 list. It covers the currencies the
    business actually deals with today; the underlying database column is a
    plain string, so supporting an additional currency later is a data
    change, not a schema migration.
    """

    AED = "AED"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    SAR = "SAR"


DEFAULT_CURRENCY = Currency.AED


class ProjectStatus(StrEnum):
    LEAD = "LEAD"
    TENDERING = "TENDERING"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    LOST = "LOST"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class QuotationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISED = "REVISED"
    WON = "WON"
    LOST = "LOST"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class VendorType(StrEnum):
    SUPPLIER = "SUPPLIER"
    SUBCONTRACTOR = "SUBCONTRACTOR"


class InvoiceDirection(StrEnum):
    CLIENT = "CLIENT"
    VENDOR = "VENDOR"


class PurchaseRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PurchaseOrderStatus(StrEnum):
    """Mirrors the VINCO frontend's real `po_status` vocabulary (see
    API_ARCHITECTURE.md) so the existing Purchase Orders page can be
    wired to this API without inventing a second status vocabulary."""

    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class ReceiptStatus(StrEnum):
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "BANK_TRANSFER"
    CHEQUE = "CHEQUE"
    CASH = "CASH"
    CARD = "CARD"
    OTHER = "OTHER"


class ContractStatus(StrEnum):
    """Lifecycle of a `Contract` once a quotation has been awarded.
    Deliberately no amendment/versioning states -- a value change after
    signing is a `ProjectVariation`, exactly like a post-award change to
    `Project.contract_value` (see `quotation_service.mark_awarded`)."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class VariationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CostPaymentStatus(StrEnum):
    """Whether an ActualCost has been paid, tracked independently of any
    linked vendor Invoice (which may not exist yet for a cost that has only
    been recorded from a receipt/reference)."""

    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class DocumentType(StrEnum):
    QUOTATION = "QUOTATION"
    BOQ = "BOQ"
    CONTRACT = "CONTRACT"
    INVOICE = "INVOICE"
    DRAWING = "DRAWING"
    PHOTO = "PHOTO"
    CORRESPONDENCE = "CORRESPONDENCE"
    OTHER = "OTHER"


class DocumentSourceType(StrEnum):
    """Where an imported document's bytes actually live. LOCAL is the only
    source Phase 4 implements; GOOGLE_DRIVE is reserved so the staging
    model doesn't need a schema change when Drive sync is added later."""

    LOCAL = "LOCAL"
    GOOGLE_DRIVE = "GOOGLE_DRIVE"


class ImportDocumentKind(StrEnum):
    """What an imported document appears to represent, decided by the
    importer/normalizer from its content — never trusted blindly, always
    reviewable."""

    QUOTATION = "QUOTATION"
    BOQ = "BOQ"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    UNKNOWN = "UNKNOWN"


class ExtractionStatus(StrEnum):
    """Progress of turning a source file's bytes into candidate data.
    Independent of ReviewStatus: a document can be EXTRACTION_COMPLETE and
    still be awaiting human review."""

    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    EXTRACTION_COMPLETE = "EXTRACTION_COMPLETE"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    OCR_REQUIRED = "OCR_REQUIRED"
    #: More than one distinct quotation reference was found in a single
    #: staged file (a real archive scan bundling several quotations into
    #: one PDF) — no candidate is built, since it can't be attributed to
    #: any one of them without risking a spliced record. Never reachable
    #: for a document that genuinely contains exactly one quotation.
    MULTIPLE_QUOTATIONS_DETECTED = "MULTIPLE_QUOTATIONS_DETECTED"
    #: OCR succeeded and page-boundary segmentation proposed one or more
    #: `ImportedDocumentSegment` rows for this document (see
    #: `app.core.import_segmentation`). No `ImportedQuotationCandidate` has
    #: been created for any segment yet — that only happens after every
    #: segment has been reviewer-resolved (accepted or excluded) and
    #: `app.services.import_service.lock_segments` has run. Only ever set
    #: for `extraction_engine == "ocr"` documents; the deterministic Phase
    #: 4 path never produces segments and never enters this status.
    SEGMENTS_PROPOSED = "SEGMENTS_PROPOSED"


class ImportReviewStatus(StrEnum):
    """Where a staged document sits in the human review/confirmation
    workflow. NEEDS_REVIEW is the starting point once extraction has
    produced (or failed to produce) candidate data."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ConfidenceLevel(StrEnum):
    """Categorical extraction confidence. Deliberately not a percentage —
    the deterministic parsers in Phase 4 have no statistically meaningful
    accuracy model, so presenting "98% confidence" would be fabricated
    precision. See IMPORT_ARCHITECTURE.md."""

    HIGH = "HIGH"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    LOW = "LOW"


class ImportAuditEventType(StrEnum):
    IMPORTED = "IMPORTED"
    EXTRACTED = "EXTRACTED"
    EDITED = "EDITED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    #: A segment boundary was proposed, accepted, moved, split, merged, or
    #: excluded — see `app.services.import_service`'s segment functions.
    SEGMENTED = "SEGMENTED"


class SegmentReviewStatus(StrEnum):
    """Lifecycle of one `ImportedDocumentSegment`'s page-range boundary and
    (once locked) its own confirmation state — a single status axis rather
    than two, since a segment's boundary and its confirmation are strictly
    sequential (see IMPORT_ARCHITECTURE.md's sequential segmentation
    section): a segment can't be confirmed before it's locked, and can't be
    locked before its boundary is accepted.

    PROPOSED -> ACCEPTED -> LOCKED -> CONFIRMED | REJECTED
    PROPOSED -> EXCLUDED_NOT_A_QUOTATION (terminal; never produces a
        candidate, from either PROPOSED or ACCEPTED)

    No boundary — including a HIGH-confidence one — reaches LOCKED without
    an explicit reviewer action moving it through ACCEPTED first. There is
    deliberately no automatic PROPOSED -> ACCEPTED transition anywhere in
    this application, regardless of confidence.
    """

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    LOCKED = "LOCKED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXCLUDED_NOT_A_QUOTATION = "EXCLUDED_NOT_A_QUOTATION"


class ClientAwardEvidenceMatchStatus(StrEnum):
    """How (or whether) a `ClientAwardEvidence`'s extracted reference number was
    resolved to an existing `Quotation` — see
    `app.services.client_award_evidence_service.match_quotation_for_reference`.

    Matching is exact-string only, never fuzzy/similarity-based (see
    PO_ARCHITECTURE.md): a quotation reference is an identifier, not free
    text, and guessing which quotation a garbled or absent reference
    "probably" means is exactly the false-award risk this enum exists to
    make impossible to represent silently.

    MATCHED is the only state from which award
    (`quotation_service.mark_awarded`) is ever triggered. UNMATCHED and
    AMBIGUOUS are both terminal until a human corrects the extracted
    reference and the match is re-attempted — never auto-resolved.
    """

    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"


class OcrConfidenceStatus(StrEnum):
    """Minimum-viable, document-level gate for an OCR-derived import
    candidate — deliberately just three states, not a scoring framework.
    Computed on demand from the candidate's current field values (see
    `app.core.ocr_confidence`), never persisted, so it always reflects the
    latest reviewer edits rather than a stale snapshot from extraction
    time. Meaningful only for documents extracted via OCR
    (`ImportedDocument.extraction_engine == "ocr"`); deterministic-parsed
    documents are unaffected and keep Phase 4's original review rules.

    HIGH_CONFIDENCE and REVIEW_REQUIRED are both still, and always,
    gated by the *human* reviewing and clicking Confirm — the badge is
    informational, never a bypass. BLOCKED is the one state that actually
    disables the Confirm action, because it means a mandatory financial
    field (the quotation date, or the quoted net value) is still missing
    or unresolved.
    """

    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"
