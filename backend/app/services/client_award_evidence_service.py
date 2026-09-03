"""Purchase Order matching, confirmation, and award (PO ingestion foundation).

This is the PO-side counterpart to `quotation_service.py`: the only place
a `ClientAwardEvidence` business record is created, and the only caller of
`quotation_service.mark_awarded` that is triggered by something other than
an explicit "Award" click on the Quotations screen. See
PO_ARCHITECTURE.md for the full design and `app.services.import_service`
for the staging/OCR pipeline this sits downstream of
(`stage_client_award_evidence_document` / `run_po_extraction`).

The authoritative linkage rule, unchanged from the design: a PO's
extracted `po_reference_number` must match exactly one existing
`Quotation.reference_number` (whitespace-normalized comparison only — no
fuzzy/similarity matching). Anything else (no match, more than one match)
is recorded as `ClientAwardEvidenceMatchStatus.UNMATCHED`/`AMBIGUOUS` on the
staging candidate and can never produce a `ClientAwardEvidence` row or an
award — see `app.services.po_matching.match_quotation_for_reference`,
which computes this at extraction time.

Quotation history is never touched here: `confirm_client_award_evidence_import`
only ever calls the existing, unmodified `quotation_service.mark_awarded`
(itself a one-shot, non-re-editable transition) — it never creates a
`QuotationVersion`, never edits one, and never writes to `Quotation`
directly.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.enums import (
    DEFAULT_CURRENCY,
    Currency,
    DocumentSourceType,
    ExtractionStatus,
    ImportAuditEventType,
    ImportDocumentKind,
    ImportReviewStatus,
    ClientAwardEvidenceMatchStatus,
)
from app.core.import_normalization import normalize_whitespace
from app.models import (
    ImportAuditLogEntry,
    ImportedDocument,
    ImportedClientAwardEvidenceCandidate,
    ClientAwardEvidence,
    Project,
    Quotation,
)
from app.services import quotation_service
from app.services.errors import ValidationError
from app.services.po_matching import match_quotation_for_reference

__all__ = [
    "confirm_client_award_evidence_import",
    "reject_client_award_evidence_import",
    "reconcile_unmatched_client_award_evidence",
    "list_client_award_evidence",
    "list_client_award_evidence_for_quotation",
    "get_client_award_evidence",
    "get_client_award_evidence_source_document",
    "record_client_award_evidence",
    "attach_client_award_evidence_document",
]


def _log(
    session: Session,
    document: ImportedDocument,
    event_type: ImportAuditEventType,
    *,
    note: str | None = None,
) -> None:
    # Duplicated from `app.services.import_service._log` (trivial, ~10
    # lines) rather than imported, deliberately: `import_service.py` needs
    # to call `reconcile_unmatched_client_award_evidence` below after confirming
    # a new quotation, and importing `_log` from there would make that a
    # circular import (import_service -> client_award_evidence_service ->
    # import_service). Behavior is identical.
    session.add(
        ImportAuditLogEntry(
            imported_document_id=document.id,
            event_type=event_type,
            note=note,
        )
    )


def _find_existing_client_award_evidence(session: Session, po_reference_number: str) -> ClientAwardEvidence | None:
    stmt = select(ClientAwardEvidence).where(ClientAwardEvidence.po_reference_number == po_reference_number)
    return session.execute(stmt).scalars().first()


def confirm_client_award_evidence_import(session: Session, document: ImportedDocument) -> ClientAwardEvidence:
    """Write a locally-staged, exactly-matched PO candidate into the
    `ClientAwardEvidence` table and — the first time this happens for the
    matched quotation — award it via the existing, unmodified
    `quotation_service.mark_awarded`.

    Idempotent by `ClientAwardEvidence.po_reference_number`: if a `ClientAwardEvidence`
    with this exact reference already exists (e.g. this same PO was
    already confirmed from a different staged copy, or this function is
    called twice for the same candidate), no new row and no second award
    are created — this document is simply attached to the existing
    record and marked confirmed. This is deliberately a *second*,
    independent idempotency layer on top of `stage_document`'s SHA-256
    file-hash dedup: a rescanned copy of the same physical PO produces
    different bytes (different hash) but the same reference number, and
    must still not double-award.

    Raises `ValidationError` (nothing is persisted — the caller's
    transaction is left clean to roll back) if: the document has already
    been confirmed or rejected; it has no PO candidate; the candidate's
    match status is not `MATCHED`; the matched quotation has no version
    to award; or — for a not-yet-awarded quotation — neither the PO nor
    the quotation's current version has a usable positive value to award
    with. A PO for a quotation that is *already* awarded (a second PO
    referencing the same quotation) is still recorded as additional
    evidence, but never re-triggers `mark_awarded` — `mark_awarded` itself
    is one-shot and would reject a second call anyway; this avoids
    reaching it a second time at all.
    """
    if document.review_status == ImportReviewStatus.CONFIRMED:
        raise ValidationError("This PO import has already been confirmed.")
    if document.review_status == ImportReviewStatus.REJECTED:
        raise ValidationError("This PO import was rejected. Re-import the file to confirm it instead.")

    candidate = document.client_award_evidence_candidate
    if candidate is None:
        raise ValidationError("Nothing to confirm — PO extraction did not produce any candidate data.")

    if candidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED:
        raise ValidationError(
            "This PO's reference number did not match any existing quotation. Correct the extracted "
            "reference and re-match before confirming — a PO can never be confirmed without an exact "
            "quotation match."
        )
    if candidate.match_status == ClientAwardEvidenceMatchStatus.AMBIGUOUS:
        raise ValidationError(
            "This PO's reference number matches more than one quotation "
            f"(ids: {candidate.candidate_quotation_ids}). Resolve the ambiguity manually before confirming — "
            "a PO can never be confirmed against a guessed match."
        )

    normalized_reference = normalize_whitespace(candidate.po_reference_number)
    if not normalized_reference:
        raise ValidationError("This PO has no reference number to confirm against.")

    existing = _find_existing_client_award_evidence(session, normalized_reference)
    if existing is not None:
        document.review_status = ImportReviewStatus.CONFIRMED
        document.confirmed_at = datetime.now(UTC).replace(tzinfo=None)
        document.resulting_client_award_evidence_id = existing.id
        _log(
            session,
            document,
            ImportAuditEventType.CONFIRMED,
            note=(
                f"PO reference '{normalized_reference}' was already confirmed as purchase order "
                f"#{existing.id} — attached this import to the existing record; no new record or "
                "award was created."
            ),
        )
        session.flush()
        return existing

    quotation = session.get(Quotation, candidate.matched_quotation_id)
    if quotation is None:
        raise ValidationError("The matched quotation could not be found.")

    current_version = quotation_service.get_current_version(session, quotation)
    if current_version is None:
        raise ValidationError(
            f"Quotation '{quotation.reference_number}' has no version to award."
        )

    project = quotation.project
    already_awarded = project.contract_value is not None

    contract_value: Decimal | None = None
    if not already_awarded:
        if candidate.net_value is not None and candidate.net_value > 0:
            contract_value = candidate.net_value
        elif current_version.quoted_value is not None and current_version.quoted_value > 0:
            contract_value = current_version.quoted_value

        if contract_value is None:
            raise ValidationError(
                "Cannot award: neither this PO nor the matched quotation's current version has a "
                "usable positive value. Enter a value on one of them before confirming."
            )

    try:
        currency_enum = Currency(candidate.currency) if candidate.currency else DEFAULT_CURRENCY
    except ValueError:
        currency_enum = DEFAULT_CURRENCY

    # Supplier/Vendor intelligence foundation: recorded only when the
    # vendor named on this PO (if any) was deterministically matched to
    # an existing `Vendor` at extraction time -- an UNMATCHED or
    # AMBIGUOUS vendor identity is never guessed, and never blocks
    # confirming the PO itself (see `ImportedClientAwardEvidenceCandidate`'s
    # own docstring).
    vendor_id = candidate.matched_vendor_id if candidate.vendor_match_status == ClientAwardEvidenceMatchStatus.MATCHED else None

    client_award_evidence = ClientAwardEvidence(
        quotation_id=quotation.id,
        vendor_id=vendor_id,
        po_reference_number=normalized_reference,
        po_date=candidate.po_date,
        net_value=candidate.net_value,
        tax_value=candidate.tax_value,
        gross_value=candidate.gross_value,
        currency=currency_enum,
        notes=candidate.notes,
    )
    session.add(client_award_evidence)
    session.flush()

    if already_awarded:
        client_award_evidence.awarded_quotation_version_id = project.winning_quotation_version_id
        note = (
            f"Purchase order '{normalized_reference}' confirmed against already-awarded quotation "
            f"'{quotation.reference_number}' — recorded as additional evidence; no new award was made."
        )
    else:
        quotation_service.mark_awarded(session, current_version, contract_value=contract_value)
        client_award_evidence.awarded_quotation_version_id = current_version.id
        note = (
            f"Purchase order '{normalized_reference}' confirmed and matched to quotation "
            f"'{quotation.reference_number}' — quotation version #{current_version.id} marked AWARDED "
            f"with contract value {contract_value}."
        )

    document.review_status = ImportReviewStatus.CONFIRMED
    document.confirmed_at = datetime.now(UTC).replace(tzinfo=None)
    document.resulting_client_award_evidence_id = client_award_evidence.id
    _log(session, document, ImportAuditEventType.CONFIRMED, note=note)
    session.flush()
    return client_award_evidence


def reject_client_award_evidence_import(session: Session, document: ImportedDocument, *, reason: str | None = None) -> ImportedDocument:
    if document.review_status == ImportReviewStatus.CONFIRMED:
        raise ValidationError("Cannot reject a PO import that has already been confirmed.")

    document.review_status = ImportReviewStatus.REJECTED
    document.rejected_at = datetime.now(UTC).replace(tzinfo=None)
    _log(session, document, ImportAuditEventType.REJECTED, note=reason)
    session.flush()
    return document


def reconcile_unmatched_client_award_evidence(session: Session) -> list[ClientAwardEvidence]:
    """Re-run exact-reference matching for every currently `UNMATCHED`,
    not-yet-resolved PO candidate — call this after a brand-new
    `Quotation` is created (never for a revision: a revision never
    changes `Quotation.reference_number`, so it can never newly satisfy a
    previously-unmatched PO's reference).

    This is what makes "PO arrives before its quotation" safe for
    historical batch ingestion: without it, a PO staged and left
    `UNMATCHED` because its quotation hadn't been imported yet would stay
    `UNMATCHED` forever, even after that exact quotation is imported
    later. See `app.services.import_service.confirm_import`, the only
    caller, invoked right after a new `Quotation` (not a revision) is
    created there.

    Reuses `match_quotation_for_reference` — identical exact,
    whitespace-normalized matching rules as at extraction time, no
    separate or looser logic — and `confirm_client_award_evidence_import` —
    identical award rules as a manual confirmation, including its
    one-shot `mark_awarded` guard and its "already-awarded quotation gets
    evidence-only" behavior. A candidate that newly resolves to
    `AMBIGUOUS` is updated and left for manual review, exactly as at
    extraction time, and is never auto-confirmed. A candidate that
    resolves to `MATCHED` but then fails to auto-confirm (e.g. neither
    the PO nor the quotation has a usable positive value) is left
    `MATCHED` for a human to complete manually — this never raises.
    Never touches a `CONFIRMED` or `REJECTED` document.

    Returns every `ClientAwardEvidence` created/awarded this way (empty if
    nothing was reconciled).
    """
    stmt = (
        select(ImportedClientAwardEvidenceCandidate)
        .join(ImportedDocument, ImportedClientAwardEvidenceCandidate.imported_document_id == ImportedDocument.id)
        .where(
            ImportedClientAwardEvidenceCandidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED,
            ImportedDocument.review_status == ImportReviewStatus.NEEDS_REVIEW,
        )
    )
    candidates = session.execute(stmt).scalars().all()

    reconciled: list[ClientAwardEvidence] = []
    for candidate in candidates:
        outcome = match_quotation_for_reference(session, candidate.po_reference_number)
        if outcome.status == ClientAwardEvidenceMatchStatus.UNMATCHED:
            continue  # still nothing to link -- unchanged

        candidate.match_status = outcome.status
        candidate.matched_quotation_id = outcome.quotation.id if outcome.quotation else None
        candidate.candidate_quotation_ids = (
            json.dumps(outcome.candidate_quotation_ids) if outcome.candidate_quotation_ids else None
        )
        session.flush()

        if outcome.status != ClientAwardEvidenceMatchStatus.MATCHED:
            continue  # AMBIGUOUS -- updated for review, never auto-confirmed

        try:
            reconciled.append(confirm_client_award_evidence_import(session, candidate.document))
        except ValidationError:
            continue  # matched, but not confirmable yet -- left MATCHED for manual review

    return reconciled


# --- Manual recording (the "POs Awarded by Client" screen) --------------------
#
# Everything below this line is the hand-entered counterpart to the
# OCR-import-confirmed path above. A reviewer typing a PO's details
# directly into a form is the exact same business event as an OCR
# extraction being confirmed -- the same award rules apply either way --
# but there is no `ImportedDocument`/staged candidate driving it, so it
# cannot reuse `confirm_client_award_evidence_import` itself. The
# award-value/one-shot-`mark_awarded` logic is intentionally mirrored
# here (not extracted into a shared private helper): the two callers'
# surrounding bookkeeping (staged-document audit logging vs. none) differs
# enough that a shared helper would need almost as many parameters as it
# saved lines, and `confirm_client_award_evidence_import` is left
# completely untouched to avoid any risk to its existing, already-tested
# behavior.


def list_client_award_evidence(session: Session) -> list[ClientAwardEvidence]:
    """Every recorded client award/PO, newest first -- the data behind
    the "POs Awarded by Client" screen. Eagerly loads exactly the path
    that screen needs (quotation -> project -> client, and the awarded
    version) in one query rather than N+1 lazy loads."""
    stmt = (
        select(ClientAwardEvidence)
        .where(ClientAwardEvidence.is_deleted.is_(False))
        .options(
            joinedload(ClientAwardEvidence.quotation)
            .joinedload(Quotation.project)
            .joinedload(Project.client),
            joinedload(ClientAwardEvidence.awarded_quotation_version),
        )
        .order_by(ClientAwardEvidence.id.desc())
    )
    return list(session.execute(stmt).unique().scalars().all())


def list_client_award_evidence_for_quotation(session: Session, quotation_id: int) -> list[ClientAwardEvidence]:
    """Every client award/PO recorded against one quotation -- almost
    always zero or one, but never enforced as unique here: a second PO
    confirmed against an already-awarded quotation is valid additional
    evidence (see `confirm_client_award_evidence_import`'s own
    docstring), and the same is true of a second manually-recorded one."""
    stmt = (
        select(ClientAwardEvidence)
        .where(ClientAwardEvidence.quotation_id == quotation_id, ClientAwardEvidence.is_deleted.is_(False))
        .options(joinedload(ClientAwardEvidence.awarded_quotation_version))
        .order_by(ClientAwardEvidence.id.desc())
    )
    return list(session.execute(stmt).unique().scalars().all())


def get_client_award_evidence(session: Session, client_award_evidence_id: int) -> ClientAwardEvidence | None:
    evidence = session.get(ClientAwardEvidence, client_award_evidence_id)
    if evidence is None or evidence.is_deleted:
        return None
    return evidence


def get_client_award_evidence_source_document(
    session: Session, client_award_evidence_id: int
) -> ImportedDocument | None:
    """The original file this award traces back to, if any --
    `resulting_client_award_evidence_id` is set either by
    `confirm_client_award_evidence_import` (the OCR path) or by
    `attach_client_award_evidence_document` below (a PDF attached to a
    manually-recorded award). `None` for a manual award with nothing
    attached -- honest, not a missing feature: a Client PO recorded from
    a phone call or an email has no source document to show."""
    stmt = select(ImportedDocument).where(
        ImportedDocument.resulting_client_award_evidence_id == client_award_evidence_id
    )
    return session.execute(stmt).scalars().first()


def record_client_award_evidence(
    session: Session,
    quotation: Quotation,
    *,
    po_reference_number: str,
    po_date: date | None = None,
    net_value: Decimal | None = None,
    tax_value: Decimal | None = None,
    gross_value: Decimal | None = None,
    currency: Currency | None = None,
    notes: str | None = None,
) -> ClientAwardEvidence:
    """Manually record a client award/PO against `quotation` -- what a
    "Record Client PO" button on the Quotations screen calls, as
    opposed to a PO arriving through the OCR-import staging pipeline.

    Idempotent by `po_reference_number`, exactly like the import path,
    but *raises* on a duplicate here rather than silently returning the
    existing row: a form submission needs a clear "already recorded"
    error, not a silent success carrying someone else's data.

    Same one-shot award trigger as the import path: the first time any
    PO (manual or imported) is recorded against a not-yet-awarded
    quotation, this calls the existing, unmodified
    `quotation_service.mark_awarded` -- the ONLY place `Project.
    contract_value` is ever set. A second PO against an
    already-awarded quotation is recorded as additional evidence only,
    never re-awarding.

    The quotation's own `quoted_value` is never read back and
    overwritten with the awarded value -- `net_value`/`tax_value`/
    `gross_value` are stored only on this new row, independently. Any
    variance between the two is a read-time comparison the API layer
    computes, never persisted or reconciled away (see
    `schemas_sales.ClientAwardEvidenceRead.variance`).
    """
    normalized_reference = normalize_whitespace(po_reference_number)
    if not normalized_reference:
        raise ValidationError("A client PO reference number is required.")
    if _find_existing_client_award_evidence(session, normalized_reference) is not None:
        raise ValidationError(f"A client PO with reference '{normalized_reference}' is already recorded.")

    current_version = quotation_service.get_current_version(session, quotation)
    if current_version is None:
        raise ValidationError(f"Quotation '{quotation.reference_number}' has no version to award.")

    project = quotation.project
    already_awarded = project.contract_value is not None

    contract_value: Decimal | None = None
    if not already_awarded:
        if net_value is not None and net_value > 0:
            contract_value = net_value
        elif current_version.quoted_value is not None and current_version.quoted_value > 0:
            contract_value = current_version.quoted_value
        if contract_value is None:
            raise ValidationError(
                "Cannot record this award: neither the client PO nor the quotation's current "
                "version has a usable positive value. Enter an awarded value before recording."
            )

    client_award_evidence = ClientAwardEvidence(
        quotation_id=quotation.id,
        po_reference_number=normalized_reference,
        po_date=po_date,
        net_value=net_value,
        tax_value=tax_value,
        gross_value=gross_value,
        currency=currency or current_version.currency,
        notes=(notes or "").strip() or None,
    )
    session.add(client_award_evidence)
    try:
        session.flush()
    except IntegrityError as exc:
        # Defense in depth against the proactive check above racing a
        # concurrent insert of the same reference -- the DB's own unique
        # constraint is the real guarantee; this just turns it into the
        # same clean error message rather than a raw 500.
        session.rollback()
        raise ValidationError(f"A client PO with reference '{normalized_reference}' is already recorded.") from exc

    if already_awarded:
        client_award_evidence.awarded_quotation_version_id = project.winning_quotation_version_id
    else:
        quotation_service.mark_awarded(session, current_version, contract_value=contract_value)
        client_award_evidence.awarded_quotation_version_id = current_version.id

    session.flush()
    return client_award_evidence


def attach_client_award_evidence_document(
    session: Session, client_award_evidence: ClientAwardEvidence, path: Path, *, original_filename: str
) -> ImportedDocument:
    """Attach an already-uploaded client PO PDF to `client_award_evidence`
    as its source document -- reuses the exact same storage/hashing
    primitives `import_service.stage_document` uses for every other
    source document (SHA-256 dedup, `ImportedDocument` as the durable
    provenance record), imported locally rather than at module level to
    avoid a circular import (`import_service` already imports this
    module for `reconcile_unmatched_client_award_evidence`).

    Deliberately does NOT call `run_extraction`: the reviewer just
    typed every field on this award by hand, so there is nothing for
    OCR to usefully extract, and running it anyway risks the extractor
    guessing a *different* `document_kind`/quotation match than the one
    the human already confirmed -- exactly the "OCR must never create
    financial truth" rule this whole pipeline exists to enforce. The
    document is stored and marked `CONFIRMED` immediately, with
    `resulting_client_award_evidence_id` set directly; if OCR-assisted
    Client PO documents are wanted later, that is a new, explicit
    candidate/review flow, not a reason to run today's quotation/PO
    extractor against a file it was never designed to read.
    """
    from app.services.import_service import compute_file_hash, find_existing_by_hash

    path = Path(path)
    if not path.exists() or not path.is_file():
        raise ValidationError(f"File not found: {path}")

    try:
        file_size = path.stat().st_size
        file_hash = compute_file_hash(path)
    except OSError as exc:
        raise ValidationError(f"Could not read '{original_filename}': {exc}") from exc

    existing = find_existing_by_hash(session, file_hash)
    if existing is not None:
        raise ValidationError(
            f"'{original_filename}' was already uploaded on {existing.created_at:%d %b %Y} "
            f"as '{existing.filename}' (staging record #{existing.id})."
        )

    document = ImportedDocument(
        source_type=DocumentSourceType.LOCAL,
        document_kind=ImportDocumentKind.PURCHASE_ORDER,
        original_path=str(path),
        filename=original_filename,
        extension=path.suffix.lower().lstrip("."),
        file_size=file_size,
        file_hash=file_hash,
        extraction_status=ExtractionStatus.EXTRACTION_COMPLETE,
        review_status=ImportReviewStatus.CONFIRMED,
        resulting_client_award_evidence_id=client_award_evidence.id,
        confirmed_at=datetime.now(UTC).replace(tzinfo=None),
        notes="Attached directly to a manually-recorded client PO -- not OCR-extracted.",
    )
    session.add(document)
    session.flush()
    _log(
        session,
        document,
        ImportAuditEventType.CONFIRMED,
        note=f"Attached as source document for client PO #{client_award_evidence.id}, entered manually.",
    )
    session.flush()
    return document
