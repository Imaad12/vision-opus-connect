"""Historical-import dashboard aggregation (H12 of the scale-groundwork
ticket) -- pure read-only counting over `ImportedDocument`/`ImportBatch`,
reusing the existing status enums (`ExtractionStatus`, `ImportReviewStatus`)
that `import_service.py` already writes. No new business logic, no write
path, no OCR/extraction code touched.

Deliberately narrower than a full "historical entity" dashboard: this
counts only what the existing pipeline actually produces today
(quotations/BOQs, and -- via `ImportDocumentKind.PURCHASE_ORDER` --
client award evidence/POs). It does not report Customers/Contacts/Leads/
Invoices counts, because this pipeline does not extract those yet (see
IMPORT_ARCHITECTURE.md's scale-groundwork assessment) -- reporting a
count for something never extracted would be a fabricated number, not a
real gap being covered up.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ExtractionStatus, ImportDocumentKind, ImportReviewStatus
from app.models import ImportBatch, ImportedDocument

#: A document whose extraction never produced (and, per the pipeline's own
#: design, never will produce without a re-scan) usable candidate data --
#: the dashboard's "Failed" bucket. `OCR_REQUIRED` is deliberately
#: excluded: it means "still needs an OCR pass", a normal, resumable
#: in-progress state (see `_ingest_batch`'s `_RESUMABLE_EXTRACTION_STATUSES`),
#: not a failure.
_FAILED_EXTRACTION_STATUSES: tuple[ExtractionStatus, ...] = (
    ExtractionStatus.FAILED,
    ExtractionStatus.UNSUPPORTED,
    ExtractionStatus.MULTIPLE_QUOTATIONS_DETECTED,
)

#: Still working toward a candidate -- the dashboard's "Processing"
#: bucket. Mirrors `_ingest_batch`'s own resumable-status set exactly
#: (same module import, not a redefinition) so "processing" here always
#: means "a batch re-run would pick this up", never a stale label.
_PROCESSING_EXTRACTION_STATUSES: tuple[ExtractionStatus, ...] = (
    ExtractionStatus.PENDING,
    ExtractionStatus.EXTRACTING,
    ExtractionStatus.OCR_REQUIRED,
)


@dataclass(frozen=True)
class ImportDashboardSummary:
    """One row per H12's requested dashboard tile. `total` is every
    `ImportedDocument` in scope (all of them, or one batch's, depending
    on `batch_id` below) -- the other counts partition it, except
    `duplicates`, which is not a property of any `ImportedDocument` row
    at all (a duplicate never gets one -- see `ImportBatch`'s docstring)
    and is `None` unless a `batch_id` was given, since it can only be
    read off that batch's own recorded outcome."""

    total: int
    processing: int
    needs_review: int
    confirmed: int
    rejected: int
    failed: int
    duplicates: int | None
    #: Of `total`, how many are `document_kind == PURCHASE_ORDER` --
    #: client award evidence, not quotations. Included so a caller can
    #: distinguish "quotations still processing" from "POs still
    #: processing" without a second query, without inventing a new
    #: candidate-count concept `ImportedDocument` doesn't already carry.
    purchase_order_count: int


def compute_import_dashboard_summary(
    session: Session, *, batch_id: int | None = None
) -> ImportDashboardSummary:
    """Counts every `ImportedDocument` in scope by status, optionally
    scoped to one `ImportBatch` (H12's "Filter by batch"). Six plain
    `COUNT` queries rather than loading rows into Python -- correct at
    10,000s-of-documents scale, unlike `len(session.query(...).all())`.
    """
    base = select(func.count()).select_from(ImportedDocument)
    if batch_id is not None:
        base = base.where(ImportedDocument.batch_id == batch_id)

    def _count(*extra_where) -> int:
        stmt = base
        for clause in extra_where:
            stmt = stmt.where(clause)
        return session.execute(stmt).scalar_one()

    total = _count()
    processing = _count(ImportedDocument.extraction_status.in_(_PROCESSING_EXTRACTION_STATUSES))
    failed = _count(ImportedDocument.extraction_status.in_(_FAILED_EXTRACTION_STATUSES))
    confirmed = _count(ImportedDocument.review_status == ImportReviewStatus.CONFIRMED)
    rejected = _count(ImportedDocument.review_status == ImportReviewStatus.REJECTED)
    # "Needs review" means genuinely awaiting a human decision -- a
    # document that hasn't finished extracting yet (still `processing`)
    # or already failed outright isn't waiting on a reviewer, it's
    # waiting on (or done with) the pipeline itself.
    needs_review = _count(
        ImportedDocument.review_status == ImportReviewStatus.NEEDS_REVIEW,
        ImportedDocument.extraction_status.not_in(_PROCESSING_EXTRACTION_STATUSES),
        ImportedDocument.extraction_status.not_in(_FAILED_EXTRACTION_STATUSES),
    )
    purchase_order_count = _count(ImportedDocument.document_kind == ImportDocumentKind.PURCHASE_ORDER)

    duplicates: int | None = None
    if batch_id is not None:
        batch = session.get(ImportBatch, batch_id)
        duplicates = batch.skipped_duplicate_count if batch is not None else None

    return ImportDashboardSummary(
        total=total,
        processing=processing,
        needs_review=needs_review,
        confirmed=confirmed,
        rejected=rejected,
        failed=failed,
        duplicates=duplicates,
        purchase_order_count=purchase_order_count,
    )


__all__ = ["ImportDashboardSummary", "compute_import_dashboard_summary"]
