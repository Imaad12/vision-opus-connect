"""Ordering-independence for PO <-> Quotation matching (historical batch
ingestion readiness).

A batch of historical documents is not guaranteed to arrive quotation-
first: a client PO may be scanned and staged before its own quotation is
ever imported. `app.services.client_award_evidence_service.
reconcile_unmatched_client_award_evidence` — invoked automatically by
`app.services.import_service.confirm_import` whenever a brand-new
`Quotation` (never a revision) is created — is what makes that ordering
safe: a PO staged as UNMATCHED is retried, using the exact same
whitespace-normalized exact-match rule as at extraction time, the moment
a matching quotation later appears. These tests are deliberately not
adversarial OCR tests (see prior rounds for that) — every fixture is a
plain `.txt` file; what's under test is the ordering/reconciliation
business logic.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import ImportReviewStatus, ProjectStatus, ClientAwardEvidenceMatchStatus, QuotationStatus
from app.models import ClientAwardEvidence, Quotation
from app.services import client_service, project_service
from app.services.import_service import confirm_import, stage_document, stage_client_award_evidence_document
from app.services.client_award_evidence_service import reconcile_unmatched_client_award_evidence


def _write_quotation_txt(tmp_path: Path, name: str, *, reference: str, net: str = "40,000.00") -> Path:
    text = f"Quotation Number: {reference}\nQuotation Date: 01/03/2025\nNet Amount: {net}\n"
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _write_po_txt(tmp_path: Path, name: str, *, reference: str) -> Path:
    path = tmp_path / name
    path.write_text(f"Quotation Reference: {reference}\n", encoding="utf-8")
    return path


def _confirm_new_quotation(db_session: Session, path: Path):
    document = stage_document(db_session, path)
    client = client_service.create_client(db_session, name=f"Client for {path.name}")
    project = project_service.create_project(db_session, name=f"Project for {path.name}", client_id=client.id)
    return confirm_import(db_session, document, client_id=client.id, project_id=project.id)


# --- A. PO arrives first, quotation later -------------------------------------


def test_po_before_quotation_is_automatically_linked_and_awarded(db_session: Session, tmp_path: Path) -> None:
    po_path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/999/25")
    po_document = stage_client_award_evidence_document(db_session, po_path)
    assert po_document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED

    quotation_path = _write_quotation_txt(tmp_path, "quote.txt", reference="VN/QU/999/25", net="60,000.00")
    version = _confirm_new_quotation(db_session, quotation_path)

    db_session.refresh(po_document)
    candidate = po_document.client_award_evidence_candidate
    assert candidate.match_status == ClientAwardEvidenceMatchStatus.MATCHED
    assert candidate.matched_quotation_id == version.quotation_id
    assert po_document.review_status == ImportReviewStatus.CONFIRMED

    project = version.quotation.project
    db_session.refresh(project)
    assert project.status == ProjectStatus.AWARDED
    assert project.contract_value == Decimal("60000.00")
    db_session.refresh(version)
    assert version.status == QuotationStatus.WON

    pos = db_session.query(ClientAwardEvidence).all()
    assert len(pos) == 1
    assert pos[0].quotation_id == version.quotation_id


# --- B. Quotation arrives first, PO later (existing flow) ---------------------


def test_quotation_before_po_still_matches_at_extraction_time(db_session: Session, tmp_path: Path) -> None:
    quotation_path = _write_quotation_txt(tmp_path, "quote.txt", reference="VN/QU/998/25", net="30,000.00")
    version = _confirm_new_quotation(db_session, quotation_path)

    po_path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/998/25")
    po_document = stage_client_award_evidence_document(db_session, po_path)

    # Matched immediately at extraction time -- reconciliation is not even
    # needed for this ordering, and must not be required for it to work.
    assert po_document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.MATCHED
    assert po_document.client_award_evidence_candidate.matched_quotation_id == version.quotation_id


# --- C. Neither exists ----------------------------------------------------------


def test_reconciliation_with_nothing_to_reconcile_is_a_safe_no_op(db_session: Session) -> None:
    assert reconcile_unmatched_client_award_evidence(db_session) == []


def test_unrelated_quotation_does_not_disturb_an_unrelated_unmatched_po(
    db_session: Session, tmp_path: Path
) -> None:
    po_path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/997/25")
    po_document = stage_client_award_evidence_document(db_session, po_path)

    quotation_path = _write_quotation_txt(tmp_path, "quote.txt", reference="VN/QU/OTHER/25")
    _confirm_new_quotation(db_session, quotation_path)

    db_session.refresh(po_document)
    assert po_document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED
    assert db_session.query(ClientAwardEvidence).count() == 0


# --- D. PO reference does not exist, ever ---------------------------------------


def test_po_reference_that_never_matches_stays_unmatched(db_session: Session, tmp_path: Path) -> None:
    po_path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/DOES-NOT-EXIST/25")
    po_document = stage_client_award_evidence_document(db_session, po_path)

    # A handful of unrelated quotations get imported -- none of them ever
    # satisfy this PO's reference.
    for i in range(3):
        quotation_path = _write_quotation_txt(tmp_path, f"quote{i}.txt", reference=f"VN/QU/{i}/25")
        _confirm_new_quotation(db_session, quotation_path)

    db_session.refresh(po_document)
    assert po_document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED
    assert db_session.query(ClientAwardEvidence).count() == 0


# --- E. Ambiguous reference never awards ----------------------------------------


def test_reconciliation_to_an_ambiguous_reference_never_awards(db_session: Session, tmp_path: Path) -> None:
    """Two quotations whose reference numbers differ only by incidental
    whitespace (a real, DB-legal state -- the unique constraint is on the
    raw stored string) must never be silently resolved to either one, even
    when the ambiguity only appears after a PO was already staged."""
    po_path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/AMBIG/25")
    po_document = stage_client_award_evidence_document(db_session, po_path)
    assert po_document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED

    # A pre-existing quotation whose reference differs only by a leading
    # space -- inserted directly (bypassing the service's own stripping)
    # to construct the real, DB-legal near-duplicate state.
    client = client_service.create_client(db_session, name="Ambiguous Client")
    project = project_service.create_project(db_session, name="Ambiguous Project", client_id=client.id)
    db_session.add(Quotation(project_id=project.id, reference_number=" VN/QU/AMBIG/25"))
    db_session.flush()

    # Now a second, brand-new quotation with the exact reference is
    # imported -- this is the event that triggers reconciliation.
    quotation_path = _write_quotation_txt(tmp_path, "quote.txt", reference="VN/QU/AMBIG/25")
    _confirm_new_quotation(db_session, quotation_path)

    db_session.refresh(po_document)
    candidate = po_document.client_award_evidence_candidate
    assert candidate.match_status == ClientAwardEvidenceMatchStatus.AMBIGUOUS
    assert po_document.review_status == ImportReviewStatus.NEEDS_REVIEW
    assert db_session.query(ClientAwardEvidence).count() == 0


# --- F. Duplicate PO stays idempotent through reconciliation --------------------


def test_two_pos_staged_for_the_same_not_yet_existing_quotation_reconcile_idempotently(
    db_session: Session, tmp_path: Path
) -> None:
    """Two independently-staged PO documents citing the same reference
    (e.g. an original scan and a rescanned copy) both arrive before the
    quotation does. When the quotation is later imported, both are
    reconciled, but only one `ClientAwardEvidence` is ever created -- the
    second is idempotently attached, exactly like the existing duplicate-
    import behavior."""
    po_path_a = _write_po_txt(tmp_path, "po_a.txt", reference="VN/QU/996/25")
    po_document_a = stage_client_award_evidence_document(db_session, po_path_a)
    po_path_b = _write_po_txt(tmp_path, "po_b.txt", reference="VN/QU/996/25")
    po_document_b = stage_client_award_evidence_document(db_session, po_path_b, allow_duplicate=True)

    quotation_path = _write_quotation_txt(tmp_path, "quote.txt", reference="VN/QU/996/25", net="70,000.00")
    version = _confirm_new_quotation(db_session, quotation_path)

    db_session.refresh(po_document_a)
    db_session.refresh(po_document_b)
    assert po_document_a.review_status == ImportReviewStatus.CONFIRMED
    assert po_document_b.review_status == ImportReviewStatus.CONFIRMED
    assert po_document_a.resulting_client_award_evidence_id == po_document_b.resulting_client_award_evidence_id

    assert db_session.query(ClientAwardEvidence).count() == 1
    project = version.quotation.project
    db_session.refresh(project)
    assert project.contract_value == Decimal("70000.00")


# --- G. Already-awarded quotation via reconciliation is never re-awarded ------


def test_reconciliation_never_reprocesses_an_already_confirmed_po(db_session: Session, tmp_path: Path) -> None:
    """The first award can legitimately happen via reconciliation (case A).
    `reconcile_unmatched_client_award_evidence` is called again afterward
    (simulating a second, unrelated quotation import elsewhere triggering
    another reconciliation pass) and must be a safe no-op for the
    already-confirmed PO -- it is excluded by construction (its
    candidate's `match_status` is no longer `UNMATCHED` and its
    document's `review_status` is no longer `NEEDS_REVIEW`), so no second
    `ClientAwardEvidence` and no second award attempt are possible."""
    po_path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/995/25")
    stage_client_award_evidence_document(db_session, po_path)

    quotation_path = _write_quotation_txt(tmp_path, "quote.txt", reference="VN/QU/995/25", net="20,000.00")
    version = _confirm_new_quotation(db_session, quotation_path)
    project = version.quotation.project
    db_session.refresh(project)
    assert project.contract_value == Decimal("20000.00")
    assert db_session.query(ClientAwardEvidence).count() == 1

    # A later, unrelated reconciliation pass (e.g. triggered by importing
    # some other quotation entirely) must not touch this already-confirmed
    # PO at all.
    reconciled_again = reconcile_unmatched_client_award_evidence(db_session)

    assert reconciled_again == []
    assert db_session.query(ClientAwardEvidence).count() == 1
    db_session.refresh(project)
    assert project.contract_value == Decimal("20000.00")
