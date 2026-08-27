"""Business-correctness tests for PO ingestion (PO_ARCHITECTURE.md).

Deliberately not an adversarial OCR test suite (see the task that
introduced this file): every fixture here is a plain `.txt` file, so the
deterministic text importer is exercised directly and OCR quality is not
what's under test. What IS under test is the PO -> quotation business
relationship: exact-match award, unmatched/ambiguous handling,
idempotency, quotation-history preservation, and rollback safety —
exactly the scenarios the task called out by name.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.enums import ImportReviewStatus, ProjectStatus, ClientAwardEvidenceMatchStatus, QuotationStatus
from app.models import Project, ClientAwardEvidence, Quotation, QuotationVersion
from app.services import client_service, project_service, quotation_service
from app.services.errors import ValidationError
from app.services.import_service import compute_file_hash, stage_client_award_evidence_document
from app.services.client_award_evidence_service import confirm_client_award_evidence_import, reject_client_award_evidence_import


def _write_po_txt(
    tmp_path: Path, name: str, *, reference: str | None, po_date: str = "10/01/2025", net: str | None = "50,000.00"
) -> Path:
    lines = [f"PO Date: {po_date}"]
    if reference is not None:
        lines.append(f"Quotation Reference: {reference}")
    if net is not None:
        lines.append(f"Net Amount: {net}")
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _create_quotation(
    session: Session,
    *,
    reference: str,
    quoted_value: Decimal | None = Decimal("50000.00"),
    issued_date: date | None = date(2025, 1, 1),
) -> tuple[Project, QuotationVersion]:
    client = client_service.create_client(session, name=f"Client for {reference}")
    project = project_service.create_project(session, name=f"Project for {reference}", client_id=client.id)
    version = quotation_service.create_quotation(
        session, project, reference_number=reference, quoted_value=quoted_value, issued_date=issued_date
    )
    return project, version


# --- 1. Exact match -> attach + award -----------------------------------------


def test_exact_match_attaches_po_and_awards_the_quotation(db_session: Session, tmp_path: Path) -> None:
    project, version = _create_quotation(db_session, reference="VN/QU/500/25")
    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/500/25", net="55,000.00")

    document = stage_client_award_evidence_document(db_session, path)
    assert document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.MATCHED

    po = confirm_client_award_evidence_import(db_session, document)

    assert po.quotation_id == version.quotation_id
    assert po.awarded_quotation_version_id == version.id
    assert po.net_value == Decimal("55000.00")

    db_session.refresh(project)
    assert project.status == ProjectStatus.AWARDED
    assert project.contract_value == Decimal("55000.00")
    assert project.winning_quotation_version_id == version.id

    db_session.refresh(version)
    assert version.status == QuotationStatus.WON

    db_session.refresh(document)
    assert document.review_status == ImportReviewStatus.CONFIRMED
    assert document.resulting_client_award_evidence_id == po.id


def test_real_two_column_bleed_reference_matches_and_awards_end_to_end(
    db_session: Session, tmp_path: Path
) -> None:
    """Full real-archive acceptance round: the exact real OCR line from a
    genuine client PO (WAHAH Electric Supply Co., WES-PO29973) --
    'Fax 966138674567 Your/Vendor Ref. | QQUTNO# 26-53', a two-column PO
    header table bled onto one line -- run through the actual
    `stage_client_award_evidence_document` -> `confirm_client_award_evidence_import`
    pipeline end to end, not just the extraction unit (already covered
    separately in test_po_extraction.py). Confirms the full MATCHED ->
    award path holds for this exact real pattern, not merely that the
    field gets extracted in isolation.
    """
    # The PO's own net_value is not recovered from this real line shape
    # either (a separate, already-known limitation) -- award falls back to
    # the quotation's own quoted_value, exactly as `confirm_client_award_evidence_import`
    # is designed to when the PO carries no usable positive value of its own.
    project, version = _create_quotation(db_session, reference="QQUTNO# 26-53", quoted_value=Decimal("8850.00"))
    path = tmp_path / "wes_po.txt"
    path.write_text("Fax 966138674567 Your/Vendor Ref. | QQUTNO# 26-53\n", encoding="utf-8")

    document = stage_client_award_evidence_document(db_session, path)
    assert document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.MATCHED
    assert document.client_award_evidence_candidate.matched_quotation_id == version.quotation_id

    po = confirm_client_award_evidence_import(db_session, document)

    assert po.quotation_id == version.quotation_id
    db_session.refresh(project)
    assert project.status == ProjectStatus.AWARDED
    assert project.contract_value == Decimal("8850.00")
    db_session.refresh(version)
    assert version.status == QuotationStatus.WON


def test_po_attaches_to_the_correct_quotation_among_several(db_session: Session, tmp_path: Path) -> None:
    _project_a, version_a = _create_quotation(db_session, reference="VN/QU/701/25")
    project_b, version_b = _create_quotation(db_session, reference="VN/QU/702/25")

    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/702/25", net="90,000.00")
    document = stage_client_award_evidence_document(db_session, path)
    po = confirm_client_award_evidence_import(db_session, document)

    assert po.quotation_id == version_b.quotation_id
    assert po.quotation_id != version_a.quotation_id
    db_session.refresh(project_b)
    assert project_b.contract_value == Decimal("90000.00")


# --- 2. Reference not found ----------------------------------------------------


def test_unmatched_reference_is_flagged_and_cannot_be_confirmed(db_session: Session, tmp_path: Path) -> None:
    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/NO-SUCH-QUOTATION/25")
    document = stage_client_award_evidence_document(db_session, path)

    assert document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED

    with pytest.raises(ValidationError, match="did not match"):
        confirm_client_award_evidence_import(db_session, document)

    assert db_session.query(ClientAwardEvidence).count() == 0
    assert document.review_status == ImportReviewStatus.NEEDS_REVIEW


def test_po_with_no_reference_at_all_is_unmatched(db_session: Session, tmp_path: Path) -> None:
    path = _write_po_txt(tmp_path, "po.txt", reference=None)
    document = stage_client_award_evidence_document(db_session, path)

    assert document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED
    assert document.client_award_evidence_candidate.po_reference_number is None


# --- 3. Ambiguous match ---------------------------------------------------------


def test_ambiguous_match_is_flagged_and_cannot_be_confirmed(db_session: Session, tmp_path: Path) -> None:
    """Two quotations whose reference numbers differ only by incidental
    whitespace (a real, DB-legal state — the unique constraint is on the
    raw stored string) must never be silently resolved to either one."""
    client = client_service.create_client(db_session, name="Ambiguous Client")
    project = project_service.create_project(db_session, name="Ambiguous Project", client_id=client.id)
    db_session.add_all(
        [
            Quotation(project_id=project.id, reference_number="VN/QU/777/25"),
            Quotation(project_id=project.id, reference_number=" VN/QU/777/25"),
        ]
    )
    db_session.flush()

    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/777/25")
    document = stage_client_award_evidence_document(db_session, path)

    assert document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.AMBIGUOUS
    candidate_ids = json.loads(document.client_award_evidence_candidate.candidate_quotation_ids)
    assert len(candidate_ids) == 2

    with pytest.raises(ValidationError, match="more than one quotation"):
        confirm_client_award_evidence_import(db_session, document)

    assert db_session.query(ClientAwardEvidence).count() == 0


# --- 4. Duplicate PO import is idempotent ---------------------------------------


def test_reimporting_the_same_po_reference_does_not_duplicate_or_reaward(db_session: Session, tmp_path: Path) -> None:
    project, _version = _create_quotation(db_session, reference="VN/QU/600/25")

    path_a = _write_po_txt(tmp_path, "po_a.txt", reference="VN/QU/600/25", net="70,000.00")
    doc_a = stage_client_award_evidence_document(db_session, path_a)
    po_a = confirm_client_award_evidence_import(db_session, doc_a)

    # A rescanned copy of the exact same physical PO -- different bytes/
    # hash from path_a, but the same reference number. This is the
    # realistic duplicate scenario file-hash dedup alone cannot catch.
    path_b = _write_po_txt(tmp_path, "po_b_rescanned.txt", reference="VN/QU/600/25", net="70,000.00")
    doc_b = stage_client_award_evidence_document(db_session, path_b, allow_duplicate=True)
    po_b = confirm_client_award_evidence_import(db_session, doc_b)

    assert po_b.id == po_a.id
    assert db_session.query(ClientAwardEvidence).count() == 1
    db_session.refresh(project)
    assert project.contract_value == Decimal("70000.00")


def test_confirming_the_same_document_twice_is_rejected(db_session: Session, tmp_path: Path) -> None:
    _create_quotation(db_session, reference="VN/QU/970/25")
    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/970/25")
    document = stage_client_award_evidence_document(db_session, path)
    confirm_client_award_evidence_import(db_session, document)

    with pytest.raises(ValidationError, match="already been confirmed"):
        confirm_client_award_evidence_import(db_session, document)


# --- 5/7. Quotation history preserved; award created correctly -----------------


def test_confirming_po_does_not_alter_quotation_version_history(db_session: Session, tmp_path: Path) -> None:
    _project, version = _create_quotation(
        db_session, reference="VN/QU/800/25", quoted_value=Decimal("40000.00"), issued_date=date(2025, 2, 1)
    )
    original_issued_date = version.issued_date
    original_quoted_value = version.quoted_value
    original_version_number = version.version_number

    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/800/25", net="45,000.00")
    document = stage_client_award_evidence_document(db_session, path)
    confirm_client_award_evidence_import(db_session, document)

    versions = quotation_service.list_versions_for_quotation(db_session, version.quotation_id)
    assert len(versions) == 1
    db_session.refresh(version)
    assert version.issued_date == original_issued_date
    # The PO's own (different) value never overwrites the historical
    # quoted value -- only Project.contract_value reflects the award.
    assert version.quoted_value == original_quoted_value
    assert version.version_number == original_version_number
    assert version.status == QuotationStatus.WON


def test_po_confirmed_after_quotation_already_manually_awarded_is_evidence_only(
    db_session: Session, tmp_path: Path
) -> None:
    """A PO for a quotation that was already awarded some other way (e.g.
    manually, from the Quotations screen) is still recorded, but never
    re-awards or overwrites the existing contract value."""
    project, version = _create_quotation(db_session, reference="VN/QU/980/25", quoted_value=Decimal("60000.00"))
    quotation_service.mark_awarded(db_session, version, contract_value=Decimal("60000.00"))

    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/980/25", net="65,000.00")
    document = stage_client_award_evidence_document(db_session, path)
    po = confirm_client_award_evidence_import(db_session, document)

    assert po.quotation_id == version.quotation_id
    assert po.net_value == Decimal("65000.00")
    db_session.refresh(project)
    assert project.contract_value == Decimal("60000.00")
    db_session.refresh(version)
    assert version.status == QuotationStatus.WON


# --- 8. Failed PO processing rolls back -----------------------------------------


def test_confirm_rolls_back_when_matched_quotation_has_no_version(db_session: Session, tmp_path: Path) -> None:
    client = client_service.create_client(db_session, name="No Version Client")
    project = project_service.create_project(db_session, name="No Version Project", client_id=client.id)
    quotation = Quotation(project_id=project.id, reference_number="VN/QU/900/25")
    db_session.add(quotation)
    db_session.flush()  # deliberately no QuotationVersion created

    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/900/25")
    document = stage_client_award_evidence_document(db_session, path)
    assert document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.MATCHED

    with pytest.raises(ValidationError, match="no version to award"):
        confirm_client_award_evidence_import(db_session, document)

    assert db_session.query(ClientAwardEvidence).count() == 0
    assert document.review_status == ImportReviewStatus.NEEDS_REVIEW
    db_session.refresh(project)
    assert project.contract_value is None


def test_confirm_rolls_back_when_no_positive_value_is_available(db_session: Session, tmp_path: Path) -> None:
    project, _version = _create_quotation(db_session, reference="VN/QU/901/25", quoted_value=None)
    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/901/25", net=None)

    document = stage_client_award_evidence_document(db_session, path)
    assert document.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.MATCHED

    with pytest.raises(ValidationError, match="usable positive value"):
        confirm_client_award_evidence_import(db_session, document)

    assert db_session.query(ClientAwardEvidence).count() == 0
    db_session.refresh(project)
    assert project.contract_value is None


# --- 9. Source immutability ------------------------------------------------------


def test_source_po_file_remains_byte_identical_after_confirmation(db_session: Session, tmp_path: Path) -> None:
    _create_quotation(db_session, reference="VN/QU/950/25")
    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/950/25")
    original_bytes = path.read_bytes()
    original_hash = compute_file_hash(path)

    document = stage_client_award_evidence_document(db_session, path)
    confirm_client_award_evidence_import(db_session, document)

    assert path.read_bytes() == original_bytes
    assert compute_file_hash(path) == original_hash


# --- Rejection creates no business records --------------------------------------


def test_rejecting_po_import_creates_no_business_records(db_session: Session, tmp_path: Path) -> None:
    project, _version = _create_quotation(db_session, reference="VN/QU/960/25")
    path = _write_po_txt(tmp_path, "po.txt", reference="VN/QU/960/25")
    document = stage_client_award_evidence_document(db_session, path)

    reject_client_award_evidence_import(db_session, document, reason="test rejection")

    assert document.review_status == ImportReviewStatus.REJECTED
    assert db_session.query(ClientAwardEvidence).count() == 0
    with pytest.raises(ValidationError, match="rejected"):
        confirm_client_award_evidence_import(db_session, document)
    db_session.refresh(project)
    assert project.contract_value is None
