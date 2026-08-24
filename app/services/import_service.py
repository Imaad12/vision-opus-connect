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
    Currency,
    DocumentSourceType,
    ExtractionStatus,
    ImportAuditEventType,
    ImportReviewStatus,
)
from app.core.financial_engine import calculate_line_total
from app.core.import_extraction import extract_candidates
from app.importers.base import RawExtraction, build_default_registry
from app.models import (
    BOQ,
    BOQLineItem,
    ImportAuditLogEntry,
    ImportedBoqLineCandidate,
    ImportedDocument,
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
        )
        .where(ImportedDocument.id == document_id)
    )
    return session.execute(stmt).unique().scalar_one_or_none()


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
        }
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
        document.extraction_status = ExtractionStatus.OCR_REQUIRED
        document.extraction_error = None
        session.flush()
        return

    result = extract_candidates(raw)
    document.document_kind = result.document_kind

    candidate = ImportedQuotationCandidate(
        imported_document_id=document.id,
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

    document.extraction_status = ExtractionStatus.EXTRACTION_COMPLETE
    _log(
        session,
        document,
        ImportAuditEventType.EXTRACTED,
        note=f"Extracted {len(result.boq_rows)} BOQ row(s); document kind: {result.document_kind.value}.",
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
    if document.review_status == ImportReviewStatus.CONFIRMED:
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
    if document.review_status == ImportReviewStatus.CONFIRMED:
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
    `ImportedDocument` into a `Client`/`Project`/`Quotation`. Every
    downstream write reuses the existing Phase 1-3 services (so it obeys
    exactly the same validation and history rules a manually-entered
    quotation would), and the resulting quoted value is always a *quoted*
    figure — it never sets `Project.contract_value` (only
    `quotation_service.mark_awarded` may do that, from the Quotations
    screen, as a separate, explicit user action).

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
    if document.review_status == ImportReviewStatus.CONFIRMED:
        raise ValidationError("This import has already been confirmed.")
    if document.review_status == ImportReviewStatus.REJECTED:
        raise ValidationError("This import was rejected. Re-import the file to confirm it instead.")

    candidate = document.quotation_candidate
    if candidate is None:
        raise ValidationError("Nothing to confirm — extraction did not produce any quotation data.")

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
    boq_lines = list(document.boq_line_candidates)
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

    document.review_status = ImportReviewStatus.CONFIRMED
    document.confirmed_at = datetime.now(UTC).replace(tzinfo=None)
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


def reject_import(session: Session, document: ImportedDocument, *, reason: str | None = None) -> ImportedDocument:
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
    "stage_document",
    "run_extraction",
    "update_quotation_candidate",
    "update_boq_line_candidate",
    "confirm_import",
    "reject_import",
]
