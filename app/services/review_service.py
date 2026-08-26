"""Review-queue triage: separating what genuinely needs a human's
judgment from what only needs a routine confirm click.

Pure read/query layer — never changes a `review_status`, `match_status`,
or `SegmentReviewStatus` itself, and never confirms or rejects anything.
Reuses the existing confidence/matching mechanisms exactly as they
already work:

- Quotation-side "confident enough to confirm without inspection" reuses
  `app.core.ocr_confidence.compute_ocr_confidence_status` — the same
  function `confirm_import` itself defers to for OCR-derived candidates
  (see that module for exactly which fields/conditions it checks). This
  module applies it uniformly to every quotation candidate, deterministic
  or OCR-derived, purely for triage classification; it does not change
  which documents `confirm_import` allows through (that gate remains
  OCR-only, unchanged).
- PO-side "confident enough" is exactly `PurchaseOrderMatchStatus.MATCHED`
  — matching is already exact and deterministic, so a `MATCHED` PO has
  nothing left to inspect; `UNMATCHED`/`AMBIGUOUS` always need a human.

See PO_ARCHITECTURE.md / IMPORT_ARCHITECTURE.md for the underlying
pipelines this reports on.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.enums import (
    ExtractionStatus,
    ImportDocumentKind,
    ImportReviewStatus,
    OcrConfidenceStatus,
    PurchaseOrderMatchStatus,
    SegmentReviewStatus,
)
from app.core.ocr_confidence import compute_ocr_confidence_status
from app.models import ImportedDocument, ImportedDocumentSegment

__all__ = [
    "ReviewItem",
    "QuotationReviewQueue",
    "PurchaseOrderReviewQueue",
    "list_quotation_review_queue",
    "list_purchase_order_review_queue",
]

#: Extraction outcomes that are not "extraction is done, go judge the
#: result" -- these always need attention regardless of any candidate.
_INCOMPLETE_EXTRACTION_STATUSES = frozenset(
    {
        ExtractionStatus.PENDING,
        ExtractionStatus.EXTRACTING,
        ExtractionStatus.FAILED,
        ExtractionStatus.UNSUPPORTED,
        ExtractionStatus.OCR_REQUIRED,
        ExtractionStatus.MULTIPLE_QUOTATIONS_DETECTED,
    }
)

_UNRESOLVED_SEGMENT_STATUSES = frozenset({SegmentReviewStatus.PROPOSED, SegmentReviewStatus.ACCEPTED})


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One reviewable unit: either a whole (non-segmented) `ImportedDocument`
    or one specific segment of a segmented one."""

    document_id: int
    filename: str
    segment_id: int | None
    segment_pages: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class QuotationReviewQueue:
    needs_attention: list[ReviewItem]
    ready_to_confirm: list[ReviewItem]


@dataclass(frozen=True, slots=True)
class PurchaseOrderReviewQueue:
    needs_attention: list[ReviewItem]
    ready_to_confirm: list[ReviewItem]


def _quotation_documents(session: Session) -> list[ImportedDocument]:
    """Every not-yet-resolved document that belongs to the quotation/BOQ
    pipeline, not the PO one. `document_kind` is reliably `PURCHASE_ORDER`
    for every PO document (set explicitly at stage time — see
    `app.services.import_service.stage_purchase_order_document`); it is
    only reliably set to `QUOTATION`/`BOQ` for a *non-segmented* quotation
    document (a segmented one never gets its own `document_kind` set —
    see `app.services.import_service.propose_segments` — since the
    document as a whole no longer maps to a single candidate). Excluding
    `PURCHASE_ORDER` is therefore the correct, complete partition: anything
    left is either an explicit quotation/BOQ import or a segmented one.
    """
    stmt = (
        select(ImportedDocument)
        .options(
            joinedload(ImportedDocument.quotation_candidate),
            joinedload(ImportedDocument.boq_line_candidates),
            joinedload(ImportedDocument.segments).joinedload(ImportedDocumentSegment.quotation_candidate),
            joinedload(ImportedDocument.segments).joinedload(ImportedDocumentSegment.boq_line_candidates),
        )
        .where(
            ImportedDocument.review_status == ImportReviewStatus.NEEDS_REVIEW,
            ImportedDocument.document_kind != ImportDocumentKind.PURCHASE_ORDER,
        )
    )
    return list(session.execute(stmt).unique().scalars().all())


def list_quotation_review_queue(session: Session) -> QuotationReviewQueue:
    """Split every not-yet-confirmed quotation/BOQ document (and, for a
    segmented one, each of its segments) into `needs_attention` (a human
    must look — missing/low-confidence fields, extraction failed, boundary
    still unresolved, more than one quotation detected in one file) vs.
    `ready_to_confirm` (nothing flagged; a human still must click confirm
    — this never auto-confirms anything — but there is nothing to
    *inspect* first).
    """
    needs_attention: list[ReviewItem] = []
    ready_to_confirm: list[ReviewItem] = []

    for document in _quotation_documents(session):
        if document.extraction_status in _INCOMPLETE_EXTRACTION_STATUSES:
            needs_attention.append(
                ReviewItem(
                    document_id=document.id,
                    filename=document.filename,
                    segment_id=None,
                    segment_pages=None,
                    reason=f"Extraction did not complete cleanly ({document.extraction_status.value}).",
                )
            )
            continue

        if document.segments:
            for segment in document.segments:
                if segment.review_status in _UNRESOLVED_SEGMENT_STATUSES:
                    needs_attention.append(
                        ReviewItem(
                            document_id=document.id,
                            filename=document.filename,
                            segment_id=segment.id,
                            segment_pages=f"{segment.start_page}-{segment.end_page}",
                            reason="Segment boundary not yet accepted and locked.",
                        )
                    )
                elif segment.review_status == SegmentReviewStatus.LOCKED:
                    status = compute_ocr_confidence_status(segment.quotation_candidate, segment.boq_line_candidates)
                    item = ReviewItem(
                        document_id=document.id,
                        filename=document.filename,
                        segment_id=segment.id,
                        segment_pages=f"{segment.start_page}-{segment.end_page}",
                        reason=f"Confidence: {status.value}.",
                    )
                    (ready_to_confirm if status == OcrConfidenceStatus.HIGH_CONFIDENCE else needs_attention).append(item)
                # CONFIRMED / REJECTED segments are already resolved -- not part of the queue.
            continue

        status = compute_ocr_confidence_status(document.quotation_candidate, document.boq_line_candidates)
        item = ReviewItem(
            document_id=document.id,
            filename=document.filename,
            segment_id=None,
            segment_pages=None,
            reason=f"Confidence: {status.value}.",
        )
        (ready_to_confirm if status == OcrConfidenceStatus.HIGH_CONFIDENCE else needs_attention).append(item)

    return QuotationReviewQueue(needs_attention=needs_attention, ready_to_confirm=ready_to_confirm)


def list_purchase_order_review_queue(session: Session) -> PurchaseOrderReviewQueue:
    """Split every not-yet-confirmed PO document into `needs_attention`
    (extraction incomplete, or `UNMATCHED`/`AMBIGUOUS`) vs.
    `ready_to_confirm` (`MATCHED` — matching is already exact and
    deterministic, so there is nothing left to inspect)."""
    stmt = (
        select(ImportedDocument)
        .options(joinedload(ImportedDocument.purchase_order_candidate))
        .where(
            ImportedDocument.review_status == ImportReviewStatus.NEEDS_REVIEW,
            ImportedDocument.document_kind == ImportDocumentKind.PURCHASE_ORDER,
        )
    )
    documents = session.execute(stmt).unique().scalars().all()

    needs_attention: list[ReviewItem] = []
    ready_to_confirm: list[ReviewItem] = []

    for document in documents:
        if document.extraction_status in _INCOMPLETE_EXTRACTION_STATUSES or document.purchase_order_candidate is None:
            needs_attention.append(
                ReviewItem(
                    document_id=document.id,
                    filename=document.filename,
                    segment_id=None,
                    segment_pages=None,
                    reason=f"Extraction did not complete cleanly ({document.extraction_status.value}).",
                )
            )
            continue

        candidate = document.purchase_order_candidate
        item = ReviewItem(
            document_id=document.id,
            filename=document.filename,
            segment_id=None,
            segment_pages=None,
            reason=f"Match status: {candidate.match_status.value}.",
        )
        if candidate.match_status == PurchaseOrderMatchStatus.MATCHED:
            ready_to_confirm.append(item)
        else:
            needs_attention.append(item)

    return PurchaseOrderReviewQueue(needs_attention=needs_attention, ready_to_confirm=ready_to_confirm)
