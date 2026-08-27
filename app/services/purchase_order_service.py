"""Purchase Order matching, confirmation, and award (PO ingestion foundation).

This is the PO-side counterpart to `quotation_service.py`: the only place
a `PurchaseOrder` business record is created, and the only caller of
`quotation_service.mark_awarded` that is triggered by something other than
an explicit "Award" click on the Quotations screen. See
PO_ARCHITECTURE.md for the full design and `app.services.import_service`
for the staging/OCR pipeline this sits downstream of
(`stage_purchase_order_document` / `run_po_extraction`).

The authoritative linkage rule, unchanged from the design: a PO's
extracted `po_reference_number` must match exactly one existing
`Quotation.reference_number` (whitespace-normalized comparison only — no
fuzzy/similarity matching). Anything else (no match, more than one match)
is recorded as `PurchaseOrderMatchStatus.UNMATCHED`/`AMBIGUOUS` on the
staging candidate and can never produce a `PurchaseOrder` row or an
award — see `app.services.po_matching.match_quotation_for_reference`,
which computes this at extraction time.

Quotation history is never touched here: `confirm_purchase_order_import`
only ever calls the existing, unmodified `quotation_service.mark_awarded`
(itself a one-shot, non-re-editable transition) — it never creates a
`QuotationVersion`, never edits one, and never writes to `Quotation`
directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (
    DEFAULT_CURRENCY,
    Currency,
    ImportAuditEventType,
    ImportReviewStatus,
    PurchaseOrderMatchStatus,
)
from app.core.import_normalization import normalize_whitespace
from app.models import ImportAuditLogEntry, ImportedDocument, ImportedPurchaseOrderCandidate, PurchaseOrder, Quotation
from app.services import quotation_service
from app.services.errors import ValidationError
from app.services.po_matching import match_quotation_for_reference

__all__ = [
    "confirm_purchase_order_import",
    "reject_purchase_order_import",
    "reconcile_unmatched_purchase_orders",
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
    # to call `reconcile_unmatched_purchase_orders` below after confirming
    # a new quotation, and importing `_log` from there would make that a
    # circular import (import_service -> purchase_order_service ->
    # import_service). Behavior is identical.
    session.add(
        ImportAuditLogEntry(
            imported_document_id=document.id,
            event_type=event_type,
            note=note,
        )
    )


def _find_existing_purchase_order(session: Session, po_reference_number: str) -> PurchaseOrder | None:
    stmt = select(PurchaseOrder).where(PurchaseOrder.po_reference_number == po_reference_number)
    return session.execute(stmt).scalars().first()


def confirm_purchase_order_import(session: Session, document: ImportedDocument) -> PurchaseOrder:
    """Write a locally-staged, exactly-matched PO candidate into the
    `PurchaseOrder` table and — the first time this happens for the
    matched quotation — award it via the existing, unmodified
    `quotation_service.mark_awarded`.

    Idempotent by `PurchaseOrder.po_reference_number`: if a `PurchaseOrder`
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

    candidate = document.purchase_order_candidate
    if candidate is None:
        raise ValidationError("Nothing to confirm — PO extraction did not produce any candidate data.")

    if candidate.match_status == PurchaseOrderMatchStatus.UNMATCHED:
        raise ValidationError(
            "This PO's reference number did not match any existing quotation. Correct the extracted "
            "reference and re-match before confirming — a PO can never be confirmed without an exact "
            "quotation match."
        )
    if candidate.match_status == PurchaseOrderMatchStatus.AMBIGUOUS:
        raise ValidationError(
            "This PO's reference number matches more than one quotation "
            f"(ids: {candidate.candidate_quotation_ids}). Resolve the ambiguity manually before confirming — "
            "a PO can never be confirmed against a guessed match."
        )

    normalized_reference = normalize_whitespace(candidate.po_reference_number)
    if not normalized_reference:
        raise ValidationError("This PO has no reference number to confirm against.")

    existing = _find_existing_purchase_order(session, normalized_reference)
    if existing is not None:
        document.review_status = ImportReviewStatus.CONFIRMED
        document.confirmed_at = datetime.now(UTC).replace(tzinfo=None)
        document.resulting_purchase_order_id = existing.id
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
    # confirming the PO itself (see `ImportedPurchaseOrderCandidate`'s
    # own docstring).
    vendor_id = candidate.matched_vendor_id if candidate.vendor_match_status == PurchaseOrderMatchStatus.MATCHED else None

    purchase_order = PurchaseOrder(
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
    session.add(purchase_order)
    session.flush()

    if already_awarded:
        purchase_order.awarded_quotation_version_id = project.winning_quotation_version_id
        note = (
            f"Purchase order '{normalized_reference}' confirmed against already-awarded quotation "
            f"'{quotation.reference_number}' — recorded as additional evidence; no new award was made."
        )
    else:
        quotation_service.mark_awarded(session, current_version, contract_value=contract_value)
        purchase_order.awarded_quotation_version_id = current_version.id
        note = (
            f"Purchase order '{normalized_reference}' confirmed and matched to quotation "
            f"'{quotation.reference_number}' — quotation version #{current_version.id} marked AWARDED "
            f"with contract value {contract_value}."
        )

    document.review_status = ImportReviewStatus.CONFIRMED
    document.confirmed_at = datetime.now(UTC).replace(tzinfo=None)
    document.resulting_purchase_order_id = purchase_order.id
    _log(session, document, ImportAuditEventType.CONFIRMED, note=note)
    session.flush()
    return purchase_order


def reject_purchase_order_import(session: Session, document: ImportedDocument, *, reason: str | None = None) -> ImportedDocument:
    if document.review_status == ImportReviewStatus.CONFIRMED:
        raise ValidationError("Cannot reject a PO import that has already been confirmed.")

    document.review_status = ImportReviewStatus.REJECTED
    document.rejected_at = datetime.now(UTC).replace(tzinfo=None)
    _log(session, document, ImportAuditEventType.REJECTED, note=reason)
    session.flush()
    return document


def reconcile_unmatched_purchase_orders(session: Session) -> list[PurchaseOrder]:
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
    separate or looser logic — and `confirm_purchase_order_import` —
    identical award rules as a manual confirmation, including its
    one-shot `mark_awarded` guard and its "already-awarded quotation gets
    evidence-only" behavior. A candidate that newly resolves to
    `AMBIGUOUS` is updated and left for manual review, exactly as at
    extraction time, and is never auto-confirmed. A candidate that
    resolves to `MATCHED` but then fails to auto-confirm (e.g. neither
    the PO nor the quotation has a usable positive value) is left
    `MATCHED` for a human to complete manually — this never raises.
    Never touches a `CONFIRMED` or `REJECTED` document.

    Returns every `PurchaseOrder` created/awarded this way (empty if
    nothing was reconciled).
    """
    stmt = (
        select(ImportedPurchaseOrderCandidate)
        .join(ImportedDocument, ImportedPurchaseOrderCandidate.imported_document_id == ImportedDocument.id)
        .where(
            ImportedPurchaseOrderCandidate.match_status == PurchaseOrderMatchStatus.UNMATCHED,
            ImportedDocument.review_status == ImportReviewStatus.NEEDS_REVIEW,
        )
    )
    candidates = session.execute(stmt).scalars().all()

    reconciled: list[PurchaseOrder] = []
    for candidate in candidates:
        outcome = match_quotation_for_reference(session, candidate.po_reference_number)
        if outcome.status == PurchaseOrderMatchStatus.UNMATCHED:
            continue  # still nothing to link -- unchanged

        candidate.match_status = outcome.status
        candidate.matched_quotation_id = outcome.quotation.id if outcome.quotation else None
        candidate.candidate_quotation_ids = (
            json.dumps(outcome.candidate_quotation_ids) if outcome.candidate_quotation_ids else None
        )
        session.flush()

        if outcome.status != PurchaseOrderMatchStatus.MATCHED:
            continue  # AMBIGUOUS -- updated for review, never auto-confirmed

        try:
            reconciled.append(confirm_purchase_order_import(session, candidate.document))
        except ValidationError:
            continue  # matched, but not confirmable yet -- left MATCHED for manual review

    return reconciled
