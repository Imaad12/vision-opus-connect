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
