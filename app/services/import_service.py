"""Local document import: staging, extraction, review, and confirmation.

This is the only module that turns an `ImportedDocument` into business
records (`Client`, `Project`, `Quotation`, `QuotationVersion`, `BOQ`,
`BOQLineItem`) — and only ever via `confirm_import`, and only once, and
only using the existing `client_service`/`project_service`/
`quotation_service` functions (never duplicating their validation or the
financial engine). See IMPORT_ARCHITECTURE.md for the full pipeline:

    local file -> stage_document -> run_extraction -> human review
    (update_quotation_candidate / update_boq_line_candidate)
    -> confirm_import (writes business records) | reject_import (no-op on business data)

Nothing in this module ever computes or stores a profit, margin, or actual
cost. `candidate.net_value` becomes `QuotationVersion.quoted_value` — a
*quoted* figure — never `Project.contract_value` (that only happens via
`quotation_service.mark_awarded`, unchanged from Phase 3, which the user
must still explicitly trigger from the Quotations screen after import).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.enums import (
    DEFAULT_CURRENCY,
    ConfidenceLevel,
    Currency,
    DocumentSourceType,
    ExtractionStatus,
    ImportAuditEventType,
    ImportReviewStatus,
    OcrConfidenceStatus,
    SegmentReviewStatus,
)
from app.core.financial_engine import calculate_line_total
from app.core.import_extraction import extract_candidates
from app.core.import_segmentation import detect_segments, slice_raw_extraction_to_pages
from app.core.ocr_confidence import compute_ocr_confidence_status
from app.core.ocr_extraction import extract_via_ocr
from app.importers.base import ExtractedTable, RawExtraction, build_default_registry
from app.models import (
    BOQ,
    BOQLineItem,
    ImportAuditLogEntry,
    ImportedBoqLineCandidate,
    ImportedDocument,
    ImportedDocumentSegment,
    ImportedQuotationCandidate,
    Quotation,
    Trade,
)
from app.services import client_service, project_service, quotation_service
from app.services.errors import RevisionConflictError, ValidationError

logger = logging.getLogger("app.services.import_service")

_HASH_CHUNK_SIZE = 1 << 20  # 1 MiB — avoids loading a large file into memory at once

# A revision's total is considered "materially different" from an existing
# one past this tolerance — the same 1% / 1-currency-unit rule already used
# for BOQ extracted-vs-calculated amount flagging (see
# app.core.import_extraction / update_boq_line_candidate), reused here
# rather than inventing a second threshold.
_MATERIAL_DIFFERENCE_FRACTION = Decimal("0.01")
_MATERIAL_DIFFERENCE_FLOOR = Decimal("1")


# --- Hashing / duplicate detection ------------------------------------------


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_existing_by_hash(session: Session, file_hash: str) -> ImportedDocument | None:
    stmt = select(ImportedDocument).where(ImportedDocument.file_hash == file_hash).order_by(
        ImportedDocument.created_at.desc()
    )
    return session.execute(stmt).scalars().first()


def check_for_duplicate(session: Session, path: Path) -> ImportedDocument | None:
    """Compute `path`'s hash and look for a prior import of the exact same
    bytes — used by the UI *before* staging, so it can ask the user whether
    to proceed rather than either silently duplicating or silently
    blocking. Filename is never used for duplicate detection on its own,
    since a renamed copy of the same file is still the same content, and a
    different file can coincidentally share a name."""
    try:
        file_hash = compute_file_hash(path)
    except OSError:
        return None
    return find_existing_by_hash(session, file_hash)


# --- Listing -----------------------------------------------------------------


def list_imported_documents(session: Session, *, search: str | None = None) -> list[ImportedDocument]:
    stmt = select(ImportedDocument).order_by(ImportedDocument.created_at.desc())
    if search:
        stmt = stmt.where(ImportedDocument.filename.ilike(f"%{search}%"))
    return list(session.execute(stmt).scalars().all())


def get_imported_document(session: Session, document_id: int) -> ImportedDocument | None:
    stmt = (
        select(ImportedDocument)
        .options(
            joinedload(ImportedDocument.quotation_candidate),
            joinedload(ImportedDocument.boq_line_candidates),
            joinedload(ImportedDocument.audit_log),
            joinedload(ImportedDocument.resulting_client),
            joinedload(ImportedDocument.resulting_project),
            joinedload(ImportedDocument.segments).joinedload(ImportedDocumentSegment.quotation_candidate),
            joinedload(ImportedDocument.segments).joinedload(ImportedDocumentSegment.boq_line_candidates),
        )
        .where(ImportedDocument.id == document_id)
    )
    return session.execute(stmt).unique().scalar_one_or_none()


def get_segment(session: Session, segment_id: int) -> ImportedDocumentSegment | None:
    return session.get(ImportedDocumentSegment, segment_id)


def _log(
    session: Session,
    document: ImportedDocument,
    event_type: ImportAuditEventType,
    *,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    note: str | None = None,
) -> None:
    session.add(
        ImportAuditLogEntry(
            imported_document_id=document.id,
            event_type=event_type,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            note=note,
        )
    )


# --- Staging + extraction -----------------------------------------------------


def stage_document(session: Session, path: Path, *, allow_duplicate: bool = False) -> ImportedDocument:
    """Register one local file as a staged import and run extraction on it
    immediately (synchronous — acceptable at Phase 4's scale; see
    IMPORT_ARCHITECTURE.md §11 on isolating this for a future background
    worker). Never copies, moves, or modifies `path`."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise ValidationError(f"File not found: {path}")

    try:
        file_size = path.stat().st_size
        file_hash = compute_file_hash(path)
    except OSError as exc:
        raise ValidationError(f"Could not read '{path.name}': {exc}") from exc

    if not allow_duplicate:
        existing = find_existing_by_hash(session, file_hash)
        if existing is not None:
            raise ValidationError(
                f"'{path.name}' was already imported on {existing.created_at:%d %b %Y} "
                f"as '{existing.filename}' (staging record #{existing.id}). "
                "Re-import deliberately if this is intentional."
            )

    document = ImportedDocument(
        source_type=DocumentSourceType.LOCAL,
        original_path=str(path),
        filename=path.name,
        extension=path.suffix.lower().lstrip("."),
        file_size=file_size,
        file_hash=file_hash,
        extraction_status=ExtractionStatus.PENDING,
        review_status=ImportReviewStatus.NEEDS_REVIEW,
    )
    session.add(document)
    session.flush()
    _log(session, document, ImportAuditEventType.IMPORTED, note=f"Imported from {path}")
    session.flush()

    run_extraction(session, document)
    return document


def _serialize_raw_extraction(raw: RawExtraction) -> str:
    return json.dumps(
        {
            "text": raw.text,
            "tables": [dataclasses.asdict(table) for table in raw.tables],
            "warnings": raw.warnings,
            "ocr_pages": raw.ocr_pages,
        }
    )


def _deserialize_raw_extraction(data: str | None) -> RawExtraction | None:
    """Inverse of `_serialize_raw_extraction` -- reconstructs the
    `RawExtraction` a document's stored `raw_extracted_data` came from, so
    `lock_segments` can re-slice it per segment. Only the fields
    `slice_raw_extraction_to_pages` and `extract_candidates` actually need
    are restored (`requires_ocr`/`unsupported` are never true for data
    that reached this point, since `run_extraction` already returned
    before persisting it otherwise)."""
    if not data:
        return None
    payload = json.loads(data)
    return RawExtraction(
        text=payload.get("text"),
        tables=[ExtractedTable(**table) for table in payload.get("tables") or []],
        warnings=payload.get("warnings") or [],
        ocr_pages=payload.get("ocr_pages"),
    )


def run_extraction(session: Session, document: ImportedDocument) -> None:
    """Run the deterministic extraction pipeline for one staged document.
    Never raises — any failure (corrupt file, missing file, malformed
    workbook, ...) is recorded as `ExtractionStatus.FAILED` with a message,
    so one bad document can never take down the whole import batch or the
    application."""
    document.extraction_status = ExtractionStatus.EXTRACTING
    document.extraction_error = None
    session.flush()

    path = Path(document.original_path)
    if not path.exists():
        document.extraction_status = ExtractionStatus.FAILED
        document.extraction_error = "The source file could not be found — it may have been moved or deleted."
        session.flush()
        return

    registry = build_default_registry()
    importer = registry.find_for(path)
    if importer is None:
        document.extraction_status = ExtractionStatus.UNSUPPORTED
        document.extraction_error = "Unsupported file type"
        session.flush()
        return

    try:
        raw = importer.extract(path)
    except Exception as exc:  # noqa: BLE001 - a single bad document must never crash the app
        logger.exception("Extraction failed for imported document %s (%s)", document.id, document.filename)
        document.extraction_status = ExtractionStatus.FAILED
        document.extraction_error = f"Extraction failed: {exc}"
        session.flush()
        return

    document.raw_extracted_data = _serialize_raw_extraction(raw)

    if raw.unsupported:
        document.extraction_status = ExtractionStatus.UNSUPPORTED
        document.extraction_error = raw.unsupported_reason or "Unsupported file type"
        session.flush()
        return

    if raw.requires_ocr:
        try:
            ocr_raw = extract_via_ocr(path)
        except Exception as exc:  # noqa: BLE001 - matches the guarantee this function already
            # makes for the deterministic importer above: never raise out of run_extraction.
            logger.exception("OCR extraction failed for imported document %s (%s)", document.id, document.filename)
            document.extraction_status = ExtractionStatus.FAILED
            document.extraction_error = f"OCR extraction failed: {exc}"
            session.flush()
            return
        if ocr_raw.requires_ocr or ocr_raw.unsupported:
            # OCR engine unavailable, or the file couldn't even be opened
            # for OCR -- same terminal/re-attemptable states Phase 4
            # already has, never a fabricated candidate.
            document.extraction_status = (
                ExtractionStatus.UNSUPPORTED if ocr_raw.unsupported else ExtractionStatus.OCR_REQUIRED
            )
            document.extraction_error = ocr_raw.unsupported_reason
            document.raw_extracted_data = _serialize_raw_extraction(ocr_raw)
            session.flush()
            return
        raw = ocr_raw
        document.raw_extracted_data = _serialize_raw_extraction(raw)
        document.extraction_engine = "ocr"
        # OCR-only from here: propose page-range segments before any
        # candidate is built (see `propose_segments` / sequential
        # segmentation in IMPORT_ARCHITECTURE.md). A scan with no page
        # markers at all falls back to exactly the single-candidate
        # behavior below, unchanged.
        propose_segments(session, document, raw)
        return

    _build_candidate_from_extraction(session, document, raw, segment=None)


def _multi_signal_messages(result) -> list[str]:
    multi_signals: list[str] = []
    if len(result.distinct_references) > 1:
        multi_signals.append(
            f"{len(result.distinct_references)} distinct references found: "
            + ", ".join(result.distinct_references)
        )
    if len(result.distinct_dates) > 1:
        # A second, independent signal alongside distinct references --
        # needed because a real archive scan can lose the reference label
        # on one page while its date survives (or vice versa on another
        # page). Confirmed via adversarial review: reference-counting
        # alone missed a real, constructible case where a candidate spliced
        # one document's reference/date onto a different document's net
        # value, both reporting HIGH field confidence, with nothing else
        # to catch it. A single quotation only ever has one issue date, so
        # more than one found here is not a false-positive-prone signal.
        multi_signals.append(
            f"{len(result.distinct_dates)} distinct dates found: "
            + ", ".join(d.isoformat() for d in result.distinct_dates)
        )
    return multi_signals


def _build_candidate_from_extraction(
    session: Session,
    document: ImportedDocument,
    raw: RawExtraction,
    *,
    segment: ImportedDocumentSegment | None,
) -> bool:
    """Run the *unmodified* `extract_candidates` on `raw` and persist the
    resulting quotation/BOQ candidate rows, scoped to `segment` when given
    (else the whole document, Phase 4's original one-candidate shape).

    `raw` is never the whole document's extraction when `segment` is
    given -- the caller (`lock_segments`) always passes an already-sliced
    `RawExtraction` (see `app.core.import_segmentation.
    slice_raw_extraction_to_pages`), so this function has no way to see,
    and therefore cannot extract a field from, any page outside that
    segment's own accepted range. That slicing is the actual enforcement
    of the core safety invariant; this function does not re-check page
    ranges itself.

    The existing within-slice multi-document check (distinct references/
    dates) still runs regardless of `segment` -- a second line of defense
    if a slice (whether the whole document or one locked segment) still
    looks like it bundles more than one quotation. Returns `True` if a
    candidate was created, `False` if that check fired and nothing was
    created (never raises for this case -- the caller decides what a
    "no candidate" outcome means for its own status).
    """
    result = extract_candidates(raw)
    multi_signals = _multi_signal_messages(result)

    if multi_signals:
        if segment is not None:
            _log(
                session,
                document,
                ImportAuditEventType.EXTRACTED,
                note=(
                    f"Segment #{segment.segment_order} (pages {segment.start_page}-{segment.end_page}) "
                    f"still appears to contain more than one quotation ({'; '.join(multi_signals)}); "
                    "no candidate created. Split this segment further and lock again."
                ),
            )
        else:
            # This one staged file appears to bundle more than one
            # independent quotation document (a real, demonstrated risk
            # for scanned archives — see IMPORT_ARCHITECTURE.md). Building
            # a single candidate here would risk silently splicing a date
            # from one quotation onto a total from another, since field
            # extraction has no way to know two lines came from different
            # documents. No candidate/BOQ rows are created; the raw
            # OCR/page data already stored above (`raw_extracted_data`) is
            # preserved for manual review, and confirmation is blocked (no
            # candidate exists to confirm).
            document.extraction_status = ExtractionStatus.MULTIPLE_QUOTATIONS_DETECTED
            document.extraction_error = (
                "This file appears to contain more than one quotation document ("
                + "; ".join(multi_signals)
                + "). Split it into separate files and re-import each one, or enter "
                "this document's data manually."
            )
            _log(
                session,
                document,
                ImportAuditEventType.EXTRACTED,
                note=f"Multiple quotation documents detected ({'; '.join(multi_signals)}); no candidate created.",
            )
        session.flush()
        return False

    segment_kwargs = {"imported_document_segment_id": segment.id} if segment is not None else {}
    if segment is None:
        document.document_kind = result.document_kind

    candidate = ImportedQuotationCandidate(
        imported_document_id=document.id,
        **segment_kwargs,
        quotation_number=result.quotation.quotation_number,
        quotation_date=result.quotation.quotation_date,
        client_name=result.quotation.client_name,
        project_name=result.quotation.project_name,
        project_number=result.quotation.project_number,
        description=result.quotation.description,
        currency=result.quotation.currency,
        net_value=result.quotation.net_value,
        tax_value=result.quotation.tax_value,
        gross_value=result.quotation.gross_value,
        valid_until=result.quotation.valid_until,
        payment_terms=result.quotation.payment_terms,
        raw_values=json.dumps(result.quotation.raw_values),
        field_confidence=json.dumps(result.quotation.field_confidence),
    )
    session.add(candidate)

    for row in result.boq_rows:
        session.add(
            ImportedBoqLineCandidate(
                imported_document_id=document.id,
                **segment_kwargs,
                row_order=row.row_order,
                group_label=row.group_label,
                item_number=row.item_number,
                description=row.description,
                category_label=row.category_label,
                unit=row.unit,
                quantity=row.quantity,
                unit_rate=row.unit_rate,
                extracted_amount=row.extracted_amount,
                calculated_amount=row.calculated_amount,
                amount_flagged=row.amount_flagged,
            )
        )

    if segment is not None:
        # Force a clean reload of these two relationships rather than
        # mutating whatever collection/scalar state `segment` happened to
        # already hold -- an already-loaded caller-held `segment` object
        # (e.g. from a `document.segments` collection fetched before this
        # call) must see the new candidate/BOQ rows, and appending to a
        # *possibly-unloaded* collection risks an autoflush-triggered
        # lazy-load duplicating the rows just added.
        session.flush()
        session.refresh(segment, attribute_names=["quotation_candidate", "boq_line_candidates"])

    if segment is None:
        document.extraction_status = ExtractionStatus.EXTRACTION_COMPLETE
        _log(
            session,
            document,
            ImportAuditEventType.EXTRACTED,
            note=f"Extracted {len(result.boq_rows)} BOQ row(s); document kind: {result.document_kind.value}.",
        )
    else:
        _log(
            session,
            document,
            ImportAuditEventType.EXTRACTED,
            note=(
                f"Segment #{segment.segment_order} (pages {segment.start_page}-{segment.end_page}): "
                f"extracted {len(result.boq_rows)} BOQ row(s)."
            ),
        )
    session.flush()
    return True


# --- Sequential segmentation --------------------------------------------------


def propose_segments(session: Session, document: ImportedDocument, raw: RawExtraction) -> None:
    """OCR-only stage between raw extraction and candidate creation (see
    `app.core.import_segmentation` and IMPORT_ARCHITECTURE.md's sequential
    segmentation section): propose page-range segments for a scanned batch
    document. No candidate is created for any segment here — only after
    every segment has been reviewer-resolved (`accept_segment` or
    `exclude_segment`) and `lock_segments` has run.

    If the OCR text has no page markers at all (nothing to segment — a
    single-page scan, or any OCR text handed in without page structure),
    this falls back to exactly Phase 4/OCR Phase 1's original
    single-candidate behavior, so a genuinely single-document scan is
    completely unaffected by segmentation ever existing.
    """
    segments = detect_segments(raw)
    if not segments:
        _build_candidate_from_extraction(session, document, raw, segment=None)
        return

    for order, seg in enumerate(segments, start=1):
        session.add(
            ImportedDocumentSegment(
                imported_document_id=document.id,
                segment_order=order,
                start_page=seg.start_page,
                end_page=seg.end_page,
                boundary_confidence=seg.boundary_confidence,
                boundary_signals="\n".join(seg.boundary_signals) if seg.boundary_signals else None,
                detected_quotation_number=seg.quotation_number,
                detected_quotation_date=seg.quotation_date,
                review_status=SegmentReviewStatus.PROPOSED,
            )
        )
    session.flush()
    # Force a clean reload of the relationship rather than mutating
    # whatever collection state `document.segments` happened to already
    # hold -- appending to a *possibly-unloaded* collection risks an
    # autoflush-triggered lazy-load duplicating the rows just added.
    session.refresh(document, attribute_names=["segments"])
    document.extraction_status = ExtractionStatus.SEGMENTS_PROPOSED
    _log(
        session,
        document,
        ImportAuditEventType.SEGMENTED,
        note=(
            f"Proposed {len(segments)} segment(s) across pages "
            f"{segments[0].start_page}-{segments[-1].end_page}; awaiting reviewer boundary "
            "acceptance before any extraction runs."
        ),
    )
    session.flush()


def _ensure_boundary_editable(segment: ImportedDocumentSegment) -> None:
    """Raises, with no side effects, if `segment`'s boundary can no longer
    be changed -- called before any validation that depends on the
    *current* (about-to-be-superseded) page range, so a reviewer always
    learns "this is final" rather than a range error computed against
    data that's about to be invalidated anyway."""
    if segment.review_status == SegmentReviewStatus.CONFIRMED:
        raise ValidationError(
            f"Segment #{segment.segment_order} (pages {segment.start_page}-{segment.end_page}) has "
            "already been confirmed and its business records are final. Its boundary can no longer "
            "be changed; reject the resulting quotation from the Quotations screen first if it needs "
            "to be undone."
        )


def _invalidate_segment_candidate(session: Session, document: ImportedDocument, segment: ImportedDocumentSegment) -> None:
    """A segment's boundary is about to change (moved/split/merged/
    excluded) — delete any candidate/BOQ rows already built for it and
    send it back to PROPOSED so it must be re-accepted and re-locked. A
    boundary edit never patches an existing candidate across the new page
    range; the candidate is discarded and the *next* `lock_segments` call
    rebuilds it (if any) from the new, correctly-sliced pages. Safe to
    call on a segment with no candidate yet.
    """
    _ensure_boundary_editable(segment)
    if segment.quotation_candidate is not None:
        for line in list(segment.boq_line_candidates):
            session.delete(line)
        session.delete(segment.quotation_candidate)
        # Null the relationship, not just delete the row -- an
        # already-loaded `segment` object (e.g. from a `document.segments`
        # collection fetched before this call) would otherwise keep
        # pointing at a now-deleted candidate until a fresh query.
        segment.boq_line_candidates.clear()
        segment.quotation_candidate = None
        session.flush()
    segment.review_status = SegmentReviewStatus.PROPOSED
    segment.reviewer_adjusted = True


def list_segments(session: Session, document: ImportedDocument) -> list[ImportedDocumentSegment]:
    return sorted(document.segments, key=lambda s: s.segment_order)


def accept_segment(session: Session, document: ImportedDocument, segment: ImportedDocumentSegment) -> ImportedDocumentSegment:
    """Explicit reviewer action: this segment's proposed boundary is
    correct. Required before this segment can ever be locked and
    extracted — no boundary, including a HIGH-confidence one, is ever
    accepted automatically anywhere in this application."""
    if segment.review_status != SegmentReviewStatus.PROPOSED:
        raise ValidationError(
            f"Segment #{segment.segment_order} is not awaiting boundary review "
            f"(current state: {segment.review_status.value})."
        )
    segment.review_status = SegmentReviewStatus.ACCEPTED
    _log(
        session,
        document,
        ImportAuditEventType.SEGMENTED,
        note=f"Segment #{segment.segment_order} (pages {segment.start_page}-{segment.end_page}) boundary accepted.",
    )
    session.flush()
    return segment


def exclude_segment(session: Session, document: ImportedDocument, segment: ImportedDocumentSegment) -> ImportedDocumentSegment:
    """Mark this page range as not a quotation (an attachment, drawing, or
    correspondence run) — terminal; this segment never produces a
    candidate. Any candidate already built for it (if it had reached
    LOCKED) is discarded first."""
    if segment.review_status not in (
        SegmentReviewStatus.PROPOSED,
        SegmentReviewStatus.ACCEPTED,
        SegmentReviewStatus.LOCKED,
    ):
        raise ValidationError(
            f"Segment #{segment.segment_order} cannot be excluded from its current state "
            f"({segment.review_status.value})."
        )
    _invalidate_segment_candidate(session, document, segment)
    segment.review_status = SegmentReviewStatus.EXCLUDED_NOT_A_QUOTATION
    _log(
        session,
        document,
        ImportAuditEventType.SEGMENTED,
        note=f"Segment #{segment.segment_order} (pages {segment.start_page}-{segment.end_page}) excluded: not a quotation.",
    )
    session.flush()
    return segment


def move_segment_boundary(
    session: Session, document: ImportedDocument, segment: ImportedDocumentSegment, *, new_end_page: int
) -> list[ImportedDocumentSegment]:
    """Move the boundary between `segment` and the segment immediately
    following it — `new_end_page` becomes `segment`'s new end page, and
    the next segment's start page becomes `new_end_page + 1`. Both
    segments' existing candidates (if any) are invalidated per
    `_invalidate_segment_candidate`, never patched across the new range.
    """
    segments = list_segments(session, document)
    index = next((i for i, s in enumerate(segments) if s.id == segment.id), None)
    if index is None or index + 1 >= len(segments):
        raise ValidationError("There is no following segment to move this boundary against.")
    next_segment = segments[index + 1]

    # Confirmed-segment protection first, before validating the range or
    # touching any data: a reviewer must always learn "this is final"
    # rather than a range error computed against data about to be
    # invalidated anyway.
    _ensure_boundary_editable(segment)
    _ensure_boundary_editable(next_segment)

    if not (segment.start_page <= new_end_page < next_segment.end_page):
        raise ValidationError(
            f"The new boundary must land between pages {segment.start_page} and "
            f"{next_segment.end_page - 1} (inclusive)."
        )

    _invalidate_segment_candidate(session, document, segment)
    _invalidate_segment_candidate(session, document, next_segment)

    segment.end_page = new_end_page
    next_segment.start_page = new_end_page + 1
    _log(
        session,
        document,
        ImportAuditEventType.SEGMENTED,
        note=(
            f"Boundary between segment #{segment.segment_order} and #{next_segment.segment_order} "
            f"moved to after page {new_end_page}."
        ),
    )
    session.flush()
    return [segment, next_segment]


def merge_segments(
    session: Session, document: ImportedDocument, first: ImportedDocumentSegment, second: ImportedDocumentSegment
) -> ImportedDocumentSegment:
    """Merge two immediately adjacent segments into one (`first`, extended
    to cover `second`'s pages too). Use when segmentation over-split a
    single quotation. Both segments' existing candidates are invalidated;
    the merged segment must be re-accepted and re-locked."""
    if second.segment_order != first.segment_order + 1:
        raise ValidationError("Only two immediately adjacent segments can be merged.")

    _invalidate_segment_candidate(session, document, first)
    _invalidate_segment_candidate(session, document, second)

    first.end_page = second.end_page
    first.boundary_signals = "\n".join(
        s for s in (first.boundary_signals, "Merged with the following segment by reviewer.") if s
    )
    removed_order = second.segment_order
    session.delete(second)
    session.flush()
    # Force a clean reload rather than mutating whatever collection state
    # `document.segments` happened to already hold -- a bare
    # `session.delete()` marks the row for deletion but does not itself
    # update an already-loaded relationship collection a caller (or this
    # function's own `list_segments` call below) might be holding.
    session.refresh(document, attribute_names=["segments"])

    for seg in list_segments(session, document):
        if seg.segment_order > removed_order:
            seg.segment_order -= 1
    _log(
        session,
        document,
        ImportAuditEventType.SEGMENTED,
        note=f"Segment #{removed_order} merged into the preceding segment (now pages {first.start_page}-{first.end_page}).",
    )
    session.flush()
    return first


def split_segment(
    session: Session, document: ImportedDocument, segment: ImportedDocumentSegment, *, split_after_page: int
) -> tuple[ImportedDocumentSegment, ImportedDocumentSegment]:
    """Split one segment into two at `split_after_page` (which becomes the
    first piece's new last page). Use when segmentation under-split two
    quotations into one segment. The original segment's existing
    candidate, if any, is invalidated; both pieces start at PROPOSED and
    must be individually accepted and locked."""
    if not (segment.start_page <= split_after_page < segment.end_page):
        raise ValidationError(
            f"The split point must be a page between {segment.start_page} and {segment.end_page - 1} (inclusive)."
        )
    _invalidate_segment_candidate(session, document, segment)

    insertion_order = segment.segment_order + 1
    for seg in list_segments(session, document):
        if seg.segment_order >= insertion_order:
            seg.segment_order += 1

    new_segment = ImportedDocumentSegment(
        imported_document_id=document.id,
        segment_order=insertion_order,
        start_page=split_after_page + 1,
        end_page=segment.end_page,
        boundary_confidence=ConfidenceLevel.LOW.value,
        boundary_signals="Split from the preceding segment by reviewer.",
        review_status=SegmentReviewStatus.PROPOSED,
    )
    segment.end_page = split_after_page
    session.add(new_segment)
    session.flush()
    # Same reasoning as `merge_segments`: force a clean reload of
    # `document.segments` rather than appending to whatever collection
    # state it happened to already hold.
    session.refresh(document, attribute_names=["segments"])
    _log(
        session,
        document,
        ImportAuditEventType.SEGMENTED,
        note=(
            f"Segment #{segment.segment_order} split after page {split_after_page}: now pages "
            f"{segment.start_page}-{segment.end_page} and {new_segment.start_page}-{new_segment.end_page}."
        ),
    )
    session.flush()
    return segment, new_segment


def lock_segments(session: Session, document: ImportedDocument) -> None:
    """Require every segment to be reviewer-resolved (ACCEPTED or
    EXCLUDED_NOT_A_QUOTATION), then run extraction once per ACCEPTED
    segment, restricted to that segment's own sliced pages.

    This is where the core safety invariant is structurally enforced:
    `slice_raw_extraction_to_pages` builds a `RawExtraction` containing
    only that segment's own pages, and `_build_candidate_from_extraction`
    (via the unmodified `extract_candidates`) is only ever handed that
    sliced object — never the whole document's data. A page outside a
    segment's accepted range is therefore never visible to the field
    matcher that builds that segment's candidate.
    """
    segments = list_segments(session, document)
    if not segments:
        raise ValidationError("This document has no proposed segments to lock.")

    unresolved = [s for s in segments if s.review_status == SegmentReviewStatus.PROPOSED]
    if unresolved:
        pending = ", ".join(f"#{s.segment_order} (pages {s.start_page}-{s.end_page})" for s in unresolved)
        raise ValidationError(
            f"Every segment's boundary must be accepted or excluded before locking. Still awaiting "
            f"review: {pending}."
        )

    raw = _deserialize_raw_extraction(document.raw_extracted_data)
    if raw is None:
        raise ValidationError("The original extracted data for this document is no longer available.")

    locked_count = 0
    for segment in segments:
        if segment.review_status != SegmentReviewStatus.ACCEPTED:
            continue  # EXCLUDED_NOT_A_QUOTATION -- never produces a candidate
        sliced = slice_raw_extraction_to_pages(raw, segment.start_page, segment.end_page)
        created = _build_candidate_from_extraction(session, document, sliced, segment=segment)
        if created:
            segment.review_status = SegmentReviewStatus.LOCKED
            locked_count += 1
        # else: this segment's own slice still looks like more than one
        # quotation (the within-slice multi-signal check fired) --
        # `_build_candidate_from_extraction` already logged why. It stays
        # ACCEPTED with no candidate; the reviewer must split it further
        # (`split_segment`) and lock again. There is no automatic retry.

    document.extraction_status = ExtractionStatus.EXTRACTION_COMPLETE
    _log(
        session,
        document,
        ImportAuditEventType.SEGMENTED,
        note=f"Locked {locked_count} of {len(segments)} segment(s) for extraction.",
    )
    session.flush()


# --- Review / editing ---------------------------------------------------------

_QUOTATION_EDITABLE_FIELDS = (
    "quotation_number",
    "quotation_date",
    "client_name",
    "project_name",
    "project_number",
    "description",
    "currency",
    "net_value",
    "tax_value",
    "gross_value",
    "valid_until",
    "payment_terms",
    "notes",
)


def update_quotation_candidate(
    session: Session, document: ImportedDocument, candidate: ImportedQuotationCandidate, **fields: object
) -> ImportedQuotationCandidate:
    if candidate.segment is not None:
        if candidate.segment.review_status == SegmentReviewStatus.CONFIRMED:
            raise ValidationError("This segment has already been confirmed and can no longer be edited.")
    elif document.review_status == ImportReviewStatus.CONFIRMED:
        raise ValidationError("This import has already been confirmed and can no longer be edited.")

    for field_name, new_value in fields.items():
        if field_name not in _QUOTATION_EDITABLE_FIELDS:
            raise ValidationError(f"'{field_name}' is not an editable field.")
        old_value = getattr(candidate, field_name)
        if old_value == new_value:
            continue
        _log(
            session,
            document,
            ImportAuditEventType.EDITED,
            field_name=field_name,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
        )
        setattr(candidate, field_name, new_value)

    session.flush()
    return candidate


def update_boq_line_candidate(
    session: Session,
    document: ImportedDocument,
    line: ImportedBoqLineCandidate,
    *,
    description: str | None = None,
    category_label: str | None = None,
    unit: str | None = None,
    quantity: Decimal | None = None,
    unit_rate: Decimal | None = None,
    extracted_amount: Decimal | None = None,
    notes: str | None = None,
) -> ImportedBoqLineCandidate:
    if line.segment is not None:
        if line.segment.review_status == SegmentReviewStatus.CONFIRMED:
            raise ValidationError("This segment has already been confirmed and can no longer be edited.")
    elif document.review_status == ImportReviewStatus.CONFIRMED:
        raise ValidationError("This import has already been confirmed and can no longer be edited.")

    for field_name, new_value in (
        ("description", description),
        ("category_label", category_label),
        ("unit", unit),
        ("quantity", quantity),
        ("unit_rate", unit_rate),
        ("extracted_amount", extracted_amount),
        ("notes", notes),
    ):
        old_value = getattr(line, field_name)
        if old_value == new_value:
            continue
        _log(
            session,
            document,
            ImportAuditEventType.EDITED,
            field_name=f"boq_line[{line.id}].{field_name}",
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
        )
        setattr(line, field_name, new_value)

    line.calculated_amount = calculate_line_total(line.quantity, line.unit_rate)
    if line.extracted_amount is not None and line.calculated_amount is not None:
        difference = abs(line.extracted_amount - line.calculated_amount)
        tolerance = max(Decimal("1"), abs(line.extracted_amount) * Decimal("0.01"))
        line.amount_flagged = difference > tolerance
    else:
        line.amount_flagged = False

    session.flush()
    return line


# --- Confirmation / rejection --------------------------------------------------


def _totals_differ_materially(a: Decimal | None, b: Decimal | None) -> bool:
    """True if `a` and `b` are far enough apart that they can't reasonably
    be read as "the same total" — or if either is unknown, since an
    unknown total can't be confirmed to match either (conservative on
    purpose: this feeds a revision-conflict check, and guessing "probably
    fine" from missing data is exactly what this check exists to avoid)."""
    if a is None or b is None:
        return True
    difference = abs(a - b)
    tolerance = max(_MATERIAL_DIFFERENCE_FLOOR, abs(b) * _MATERIAL_DIFFERENCE_FRACTION)
    return difference > tolerance


def _detect_revision_conflict(
    candidate: ImportedQuotationCandidate, existing_version
) -> RevisionConflictError | None:
    """Compare an incoming quotation candidate against the current version
    of the existing quotation it's about to be added as a revision of.
    Returns a (not-yet-raised) `RevisionConflictError` describing the
    conflict, or `None` if there isn't one — used both to raise the error
    and, when the caller has acknowledged it, to describe what was
    acknowledged in the audit log.

    Deliberately conservative: if either date is unknown, no chronology
    comparison is possible, so no conflict is reported (this only ever
    *blocks* a comparable conflict, never a case it can't evaluate).
    """
    if existing_version is None or existing_version.issued_date is None or candidate.quotation_date is None:
        return None

    if candidate.quotation_date < existing_version.issued_date:
        conflict_type = "earlier"
    elif candidate.quotation_date == existing_version.issued_date and _totals_differ_materially(
        candidate.net_value, existing_version.quoted_value
    ):
        conflict_type = "same_date_conflict"
    else:
        return None

    reference = candidate.quotation_number
    incoming_date_str = candidate.quotation_date.isoformat()
    existing_date_str = existing_version.issued_date.isoformat()
    incoming_total_str = f"{candidate.net_value:,.2f}" if candidate.net_value is not None else "unknown"
    existing_total_str = (
        f"{existing_version.quoted_value:,.2f}" if existing_version.quoted_value is not None else "unknown"
    )

    if conflict_type == "earlier":
        reason = (
            f"The incoming document is dated {incoming_date_str}, which is earlier than the "
            f"existing quotation's current version, dated {existing_date_str}."
        )
    else:
        reason = (
            f"The incoming document has the same date ({incoming_date_str}) as the existing "
            "quotation's current version, but a materially different total — the dates alone "
            "cannot determine which one is authoritative."
        )

    message = (
        f"Quotation reference '{reference}' already exists with a conflicting revision.\n\n"
        f"Incoming: date {incoming_date_str}, total {incoming_total_str}\n"
        f"Existing (current): date {existing_date_str}, total {existing_total_str}\n\n"
        f"{reason}\n\n"
        "Confirming will add this as a new revision anyway — both documents will be preserved "
        "and neither will be overwritten. Proceed only after checking which one should actually "
        "be treated as current."
    )

    return RevisionConflictError(
        message,
        conflict_type=conflict_type,
        reference=reference,
        incoming_date=candidate.quotation_date,
        incoming_total=candidate.net_value,
        existing_date=existing_version.issued_date,
        existing_total=existing_version.quoted_value,
    )


def confirm_import(
    session: Session,
    document: ImportedDocument,
    *,
    segment: ImportedDocumentSegment | None = None,
    client_id: int | None = None,
    new_client_name: str | None = None,
    project_id: int | None = None,
    new_project_name: str | None = None,
    new_project_code: str | None = None,
    quotation_id: int | None = None,
    include_boq: bool = True,
    acknowledge_revision_conflict: bool = False,
):
    """Write the reviewed candidate data into the real business tables.
    This is the ONLY function in the application that turns an
    `ImportedDocument` (or, for a segmented OCR document, one of its
    `ImportedDocumentSegment`s) into a `Client`/`Project`/`Quotation`.
    Every downstream write reuses the existing Phase 1-3 services (so it
    obeys exactly the same validation and history rules a manually-entered
    quotation would), and the resulting quoted value is always a *quoted*
    figure — it never sets `Project.contract_value` (only
    `quotation_service.mark_awarded` may do that, from the Quotations
    screen, as a separate, explicit user action).

    Pass `segment` to confirm one locked segment of a sequentially
    segmented document (see IMPORT_ARCHITECTURE.md) — each segment
    produces its own, fully independent `Quotation`/`QuotationVersion`;
    confirming one has no effect on any sibling segment. Omit it for
    Phase 4/OCR Phase 1's original, unsegmented single-candidate
    documents — that path is completely unchanged by segmentation ever
    existing.

    When `quotation_id` targets an existing quotation, the incoming
    candidate's date is compared against that quotation's current version
    (`quotation_service.get_current_version`) before the revision is
    created. An incoming date earlier than the existing one, or an equal
    date with a materially different total, raises `RevisionConflictError`
    unless `acknowledge_revision_conflict=True` is passed — which must
    only ever come from an explicit reviewer action, never a default. This
    never overwrites or edits an existing `QuotationVersion`; an
    acknowledged conflict still creates a brand-new row, preserving both
    the existing and incoming documents' history intact.
    """
    if segment is not None:
        if segment.review_status == SegmentReviewStatus.CONFIRMED:
            raise ValidationError("This segment has already been confirmed.")
        if segment.review_status == SegmentReviewStatus.REJECTED:
            raise ValidationError("This segment was rejected. Adjust its boundary and re-lock it to confirm.")
        if segment.review_status != SegmentReviewStatus.LOCKED:
            raise ValidationError(
                "This segment must have its boundary accepted and be locked (extracted) before it "
                "can be confirmed."
            )
        candidate = segment.quotation_candidate
        boq_lines = list(segment.boq_line_candidates)
    else:
        if document.review_status == ImportReviewStatus.CONFIRMED:
            raise ValidationError("This import has already been confirmed.")
        if document.review_status == ImportReviewStatus.REJECTED:
            raise ValidationError("This import was rejected. Re-import the file to confirm it instead.")
        candidate = document.quotation_candidate
        boq_lines = list(document.boq_line_candidates)

    if candidate is None:
        raise ValidationError("Nothing to confirm — extraction did not produce any quotation data.")

    if document.extraction_engine == "ocr":
        # Defensive, service-layer gate (never trust the UI alone): an
        # OCR-derived candidate can never be confirmed while a mandatory
        # financial field is still missing/unresolved. This does not apply
        # to deterministically-parsed documents, which keep Phase 4's
        # original, unchanged behavior.
        status = compute_ocr_confidence_status(candidate, boq_lines)
        if status == OcrConfidenceStatus.BLOCKED:
            raise ValidationError(
                "This document was extracted via OCR and is missing the quotation date and/or "
                "net quoted value, so it cannot be confirmed yet. Enter both before confirming."
            )

    if client_id is not None:
        client = client_service.get_client(session, client_id)
        if client is None:
            raise ValidationError("Select a valid client.")
    elif new_client_name:
        client = client_service.create_client(session, name=new_client_name)
    else:
        raise ValidationError("Select an existing client or provide a name for a new one before confirming.")

    if project_id is not None:
        project = project_service.get_project(session, project_id)
        if project is None:
            raise ValidationError("Select a valid project.")
    elif new_project_name:
        project = project_service.create_project(
            session,
            name=new_project_name,
            client_id=client.id,
            project_code=new_project_code or candidate.project_number,
            description=candidate.description,
        )
    else:
        raise ValidationError("Select an existing project or provide a name for a new one before confirming.")

    try:
        currency_enum = Currency(candidate.currency) if candidate.currency else DEFAULT_CURRENCY
    except ValueError:
        currency_enum = DEFAULT_CURRENCY

    conflict: RevisionConflictError | None = None
    if quotation_id is not None:
        quotation = session.get(Quotation, quotation_id)
        if quotation is None:
            raise ValidationError("Select a valid quotation.")

        existing_version = quotation_service.get_current_version(session, quotation)
        conflict = _detect_revision_conflict(candidate, existing_version)
        if conflict is not None and not acknowledge_revision_conflict:
            raise conflict

        version = quotation_service.create_quotation_revision(
            session,
            quotation,
            quoted_value=candidate.net_value,
            currency=currency_enum,
            issued_date=candidate.quotation_date,
            valid_until=candidate.valid_until,
            notes=candidate.notes,
        )
    else:
        version = quotation_service.create_quotation(
            session,
            project,
            reference_number=candidate.quotation_number,
            title=candidate.description,
            quoted_value=candidate.net_value,
            currency=currency_enum,
            issued_date=candidate.quotation_date,
            valid_until=candidate.valid_until,
            notes=candidate.notes,
        )

    boq = None
    if include_boq and boq_lines:
        boq = BOQ(quotation_version_id=version.id, title=document.filename)
        session.add(boq)
        session.flush()

        trades_by_name = {trade.name.lower(): trade for trade in session.execute(select(Trade)).scalars().all()}

        for line in boq_lines:
            trade = trades_by_name.get((line.category_label or "").lower())
            total = line.extracted_amount if line.extracted_amount is not None else line.calculated_amount
            session.add(
                BOQLineItem(
                    boq_id=boq.id,
                    line_number=line.item_number,
                    description=line.description or "(no description extracted)",
                    trade_id=trade.id if trade else None,
                    unit=line.unit,
                    quantity=line.quantity,
                    unit_rate=line.unit_rate,
                    total=total,
                    currency=currency_enum,
                )
            )

    confirmed_at = datetime.now(UTC).replace(tzinfo=None)
    if segment is not None:
        segment.review_status = SegmentReviewStatus.CONFIRMED
        segment.confirmed_at = confirmed_at
        segment.resulting_client_id = client.id
        segment.resulting_project_id = project.id
        segment.resulting_quotation_id = version.quotation_id
        segment.resulting_quotation_version_id = version.id
        segment.resulting_boq_id = boq.id if boq else None
        note = (
            f"Segment #{segment.segment_order} (pages {segment.start_page}-{segment.end_page}) confirmed "
            f"into project #{project.id}, quotation version #{version.id}."
        )
    else:
        document.review_status = ImportReviewStatus.CONFIRMED
        document.confirmed_at = confirmed_at
        document.resulting_client_id = client.id
        document.resulting_project_id = project.id
        document.resulting_quotation_id = version.quotation_id
        document.resulting_quotation_version_id = version.id
        document.resulting_boq_id = boq.id if boq else None
        note = f"Confirmed into project #{project.id}, quotation version #{version.id}."

    if conflict is not None:
        note += (
            f" Reviewer acknowledged a {conflict.conflict_type} revision conflict "
            f"(incoming {conflict.incoming_date} vs. existing {conflict.existing_date})."
        )
    _log(session, document, ImportAuditEventType.CONFIRMED, note=note)
    session.flush()
    return version


def reject_import(
    session: Session,
    document: ImportedDocument,
    *,
    segment: ImportedDocumentSegment | None = None,
    reason: str | None = None,
) -> ImportedDocument:
    if segment is not None:
        if segment.review_status == SegmentReviewStatus.CONFIRMED:
            raise ValidationError("Cannot reject a segment that has already been confirmed.")
        segment.review_status = SegmentReviewStatus.REJECTED
        segment.rejected_at = datetime.now(UTC).replace(tzinfo=None)
        note = f"Segment #{segment.segment_order} (pages {segment.start_page}-{segment.end_page}) rejected."
        if reason:
            note += f" {reason}"
        _log(session, document, ImportAuditEventType.REJECTED, note=note)
        session.flush()
        return document

    if document.review_status == ImportReviewStatus.CONFIRMED:
        raise ValidationError("Cannot reject an import that has already been confirmed.")

    document.review_status = ImportReviewStatus.REJECTED
    document.rejected_at = datetime.now(UTC).replace(tzinfo=None)
    _log(session, document, ImportAuditEventType.REJECTED, note=reason)
    session.flush()
    return document


__all__ = [
    "compute_file_hash",
    "find_existing_by_hash",
    "check_for_duplicate",
    "list_imported_documents",
    "get_imported_document",
    "get_segment",
    "stage_document",
    "run_extraction",
    "propose_segments",
    "list_segments",
    "accept_segment",
    "exclude_segment",
    "move_segment_boundary",
    "merge_segments",
    "split_segment",
    "lock_segments",
    "update_quotation_candidate",
    "update_boq_line_candidate",
    "confirm_import",
    "reject_import",
]
