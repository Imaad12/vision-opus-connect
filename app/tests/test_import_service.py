from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.core.enums import ExtractionStatus, ImportReviewStatus
from app.importers.base import BaseImporter, RawExtraction
from app.services import client_service, project_service
from app.services.errors import ValidationError
from app.services.import_service import (
    check_for_duplicate,
    compute_file_hash,
    confirm_import,
    get_imported_document,
    list_imported_documents,
    reject_import,
    run_extraction,
    stage_document,
    update_quotation_candidate,
)

QUOTATION_TEXT = """\
Quotation Number: Q-2024-0091
Quotation Date: 15/03/2024
Client Name: ABC Holdings
Project Name: Villa ABC Renovation
Project Number: VC-2024-018
Net Amount: 1,250,000.00
VAT Amount: 62,500.00
Total Including VAT: 1,312,500.00
"""

BOQ_CSV = (
    "Item,Description,Trade,Unit,Qty,Rate,Amount\n"
    "1,Excavation works,Civil,m3,100,50.00,5000.00\n"
    "2,Blockwork,Civil,m2,200,75.00,15000.00\n"
)


def _write_quotation_txt(tmp_path: Path, name: str = "quote.txt") -> Path:
    path = tmp_path / name
    path.write_text(QUOTATION_TEXT, encoding="utf-8")
    return path


def _write_boq_csv(tmp_path: Path, name: str = "boq.csv") -> Path:
    path = tmp_path / name
    path.write_text(BOQ_CSV, encoding="utf-8")
    return path


# --- Hashing / duplicate detection ------------------------------------------


def test_compute_file_hash_is_stable_for_same_content(tmp_path: Path) -> None:
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_a.write_text("identical content", encoding="utf-8")
    path_b.write_text("identical content", encoding="utf-8")

    assert compute_file_hash(path_a) == compute_file_hash(path_b)


def test_compute_file_hash_differs_for_different_content(tmp_path: Path) -> None:
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_a.write_text("content one", encoding="utf-8")
    path_b.write_text("content two", encoding="utf-8")

    assert compute_file_hash(path_a) != compute_file_hash(path_b)


def test_stage_document_missing_file_raises_validation_error(db_session: Session, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        stage_document(db_session, tmp_path / "does_not_exist.txt")


def test_staging_same_file_twice_is_flagged_as_duplicate(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation_txt(tmp_path)
    stage_document(db_session, path)

    with pytest.raises(ValidationError, match="already imported"):
        stage_document(db_session, path)


def test_duplicate_detection_is_by_content_not_filename(db_session: Session, tmp_path: Path) -> None:
    path_a = _write_quotation_txt(tmp_path, "quote_a.txt")
    path_b = tmp_path / "quote_b_renamed.txt"
    path_b.write_text(QUOTATION_TEXT, encoding="utf-8")  # same bytes, different name

    stage_document(db_session, path_a)

    with pytest.raises(ValidationError, match="already imported"):
        stage_document(db_session, path_b)


def test_deliberate_reimport_is_allowed_with_flag(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation_txt(tmp_path)
    first = stage_document(db_session, path)
    second = stage_document(db_session, path, allow_duplicate=True)

    assert first.id != second.id
    assert len(list_imported_documents(db_session)) == 2


def test_check_for_duplicate_returns_existing_document(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation_txt(tmp_path)
    staged = stage_document(db_session, path)

    found = check_for_duplicate(db_session, path)

    assert found is not None
    assert found.id == staged.id


def test_check_for_duplicate_returns_none_when_new(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation_txt(tmp_path)
    assert check_for_duplicate(db_session, path) is None


# --- Staging / extraction ------------------------------------------------------


def test_stage_document_extracts_quotation_fields(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation_txt(tmp_path)
    document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert document.review_status == ImportReviewStatus.NEEDS_REVIEW
    assert document.quotation_candidate is not None
    assert document.quotation_candidate.quotation_number == "Q-2024-0091"
    assert document.quotation_candidate.client_name == "ABC Holdings"


def test_stage_document_extracts_boq_rows(db_session: Session, tmp_path: Path) -> None:
    path = _write_boq_csv(tmp_path)
    document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert len(document.boq_line_candidates) == 2
    assert document.boq_line_candidates[0].description == "Excavation works"


def test_unsupported_file_type_does_not_crash(db_session: Session, tmp_path: Path) -> None:
    path = tmp_path / "drawing.dwg"
    path.write_bytes(b"not a real dwg but irrelevant")

    document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.UNSUPPORTED
    assert document.extraction_error == "Unsupported file type"


def test_image_file_is_marked_ocr_required(db_session: Session, tmp_path: Path) -> None:
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG fake content")

    document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.OCR_REQUIRED


def test_malformed_document_extraction_failure_does_not_crash(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation_txt(tmp_path)
    document = stage_document(db_session, path)

    class ExplodingImporter(BaseImporter):
        extensions = ("txt",)

        def extract(self, path: Path) -> RawExtraction:
            raise RuntimeError("simulated catastrophic parser failure")

    class ExplodingRegistry:
        def find_for(self, path: Path) -> BaseImporter:
            return ExplodingImporter()

    with patch("app.services.import_service.build_default_registry", return_value=ExplodingRegistry()):
        run_extraction(db_session, document)

    assert document.extraction_status == ExtractionStatus.FAILED
    assert "simulated catastrophic parser failure" in document.extraction_error


def test_moved_or_deleted_source_file_fails_gracefully(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation_txt(tmp_path)
    document = stage_document(db_session, path)
    path.unlink()

    run_extraction(db_session, document)

    assert document.extraction_status == ExtractionStatus.FAILED
    assert "could not be found" in document.extraction_error.lower()


# --- Review / editing -----------------------------------------------------


def test_editing_a_field_records_an_audit_entry(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_quotation_txt(tmp_path))
    candidate = document.quotation_candidate

    update_quotation_candidate(db_session, document, candidate, client_name="ABC Holdings LLC")

    document = get_imported_document(db_session, document.id)
    assert document.quotation_candidate.client_name == "ABC Holdings LLC"
    edits = [entry for entry in document.audit_log if entry.field_name == "client_name"]
    assert len(edits) == 1
    assert edits[0].old_value == "ABC Holdings"
    assert edits[0].new_value == "ABC Holdings LLC"


def test_editing_unknown_field_is_rejected(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_quotation_txt(tmp_path))
    with pytest.raises(ValidationError):
        update_quotation_candidate(db_session, document, document.quotation_candidate, not_a_real_field="x")


# --- Confirmation / rejection --------------------------------------------------


def test_confirm_import_creates_new_client_project_and_quotation(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_quotation_txt(tmp_path))

    version = confirm_import(
        db_session,
        document,
        new_client_name="ABC Holdings",
        new_project_name="Villa ABC Renovation",
    )

    assert version.quoted_value == document.quotation_candidate.net_value
    assert version.quotation.project.name == "Villa ABC Renovation"
    assert version.quotation.project.client.name == "ABC Holdings"

    # A quotation import must never itself become an awarded contract.
    assert version.quotation.project.contract_value is None

    document = get_imported_document(db_session, document.id)
    assert document.review_status == ImportReviewStatus.CONFIRMED
    assert document.resulting_quotation_version_id == version.id
    assert document.confirmed_at is not None


def test_confirm_import_with_boq_creates_boq_line_items(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_boq_csv(tmp_path))
    # This document has no quotation-shaped fields — supply the minimum
    # ourselves the way a reviewer would before confirming.
    update_quotation_candidate(db_session, document, document.quotation_candidate, net_value=None)

    version = confirm_import(
        db_session,
        document,
        new_client_name="XYZ Contracting",
        new_project_name="Warehouse Fitout",
    )

    assert version.boq is not None
    from sqlalchemy import select

    from app.models import BOQLineItem

    items = db_session.execute(select(BOQLineItem).where(BOQLineItem.boq_id == version.boq.id)).scalars().all()
    assert len(items) == 2
    assert {item.description for item in items} == {"Excavation works", "Blockwork"}


def test_confirm_import_using_existing_client_and_project(db_session: Session, tmp_path: Path) -> None:
    client = client_service.create_client(db_session, name="ABC Holdings")
    project = project_service.create_project(db_session, name="Villa ABC Renovation", client_id=client.id)
    db_session.commit()

    document = stage_document(db_session, _write_quotation_txt(tmp_path))
    version = confirm_import(db_session, document, client_id=client.id, project_id=project.id)

    assert version.quotation.project_id == project.id
    assert version.quotation.project.client_id == client.id


def test_confirm_import_as_new_revision_of_existing_quotation(db_session: Session, tmp_path: Path) -> None:
    client = client_service.create_client(db_session, name="ABC Holdings")
    project = project_service.create_project(db_session, name="Villa ABC Renovation", client_id=client.id)
    document_one = stage_document(db_session, _write_quotation_txt(tmp_path, "v1.txt"))
    version_one = confirm_import(db_session, document_one, client_id=client.id, project_id=project.id)

    revised_path = tmp_path / "v2.txt"
    revised_path.write_text(QUOTATION_TEXT.replace("1,250,000.00", "1,300,000.00"), encoding="utf-8")
    document_two = stage_document(db_session, revised_path)
    version_two = confirm_import(
        db_session,
        document_two,
        client_id=client.id,
        project_id=project.id,
        quotation_id=version_one.quotation_id,
    )

    assert version_two.quotation_id == version_one.quotation_id
    assert version_two.version_number == version_one.version_number + 1


def test_confirm_import_twice_raises_validation_error(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_quotation_txt(tmp_path))
    confirm_import(db_session, document, new_client_name="ABC Holdings", new_project_name="Villa ABC Renovation")

    with pytest.raises(ValidationError):
        confirm_import(db_session, document, new_client_name="ABC Holdings", new_project_name="Villa ABC Renovation")


def test_confirm_import_without_client_or_project_choice_is_rejected(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_quotation_txt(tmp_path))
    with pytest.raises(ValidationError):
        confirm_import(db_session, document)


def test_reject_import_does_not_touch_business_data(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_quotation_txt(tmp_path))

    reject_import(db_session, document, reason="Duplicate of a paper quotation already entered manually.")

    document = get_imported_document(db_session, document.id)
    assert document.review_status == ImportReviewStatus.REJECTED
    assert document.rejected_at is not None
    assert document.resulting_project_id is None
    assert document.resulting_client_id is None
    assert len(project_service.list_projects(db_session)) == 0
    assert len(client_service.list_clients(db_session)) == 0


def test_reject_after_confirm_is_rejected(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_quotation_txt(tmp_path))
    confirm_import(db_session, document, new_client_name="ABC Holdings", new_project_name="Villa ABC Renovation")

    with pytest.raises(ValidationError):
        reject_import(db_session, document)


def test_confirm_after_reject_is_rejected(db_session: Session, tmp_path: Path) -> None:
    document = stage_document(db_session, _write_quotation_txt(tmp_path))
    reject_import(db_session, document)

    with pytest.raises(ValidationError):
        confirm_import(db_session, document, new_client_name="ABC Holdings", new_project_name="Villa ABC Renovation")


def test_confirm_import_failure_rolls_back_the_new_client_and_project(db_session: Session, tmp_path: Path) -> None:
    """`confirm_import` creates a client, then a project, then a quotation —
    all in one caller-managed transaction (`session_scope()` in production,
    which commits once at the end and rolls back everything on any
    exception). If the quotation step fails (e.g. a duplicate reference
    number collides with an already-committed quotation), the client and
    project it just created inside this same call must not survive a
    rollback — otherwise a failed import could still leave an orphaned,
    unlinked client/project behind.
    """
    # Pre-existing, already-committed data that the new import will collide with.
    existing_client = client_service.create_client(db_session, name="Existing Client")
    existing_project = project_service.create_project(
        db_session, name="Existing Project", client_id=existing_client.id
    )
    from app.services.quotation_service import create_quotation

    create_quotation(db_session, existing_project, reference_number="Q-DUP", quoted_value=None)
    db_session.commit()

    colliding_text = QUOTATION_TEXT.replace("Q-2024-0091", "Q-DUP")
    path = tmp_path / "colliding_quote.txt"
    path.write_text(colliding_text, encoding="utf-8")
    document = stage_document(db_session, path)
    # In production, staging a document is its own committed transaction
    # (app/ui/imports/imports_page.py opens a fresh session_scope() per
    # file) — separate from the later, also separately-scoped, confirm
    # step. Commit here so the rollback below only undoes confirm_import's
    # own work, exactly as it would in production.
    db_session.commit()

    with pytest.raises(ValidationError, match="already in use"):
        confirm_import(
            db_session,
            document,
            new_client_name="Brand New Client",
            new_project_name="Brand New Project",
        )

    # Mirror what app.database.session.session_scope() does on any exception
    # raised out of a service call: roll back the whole transaction.
    db_session.rollback()

    client_names = {c.name for c in client_service.list_clients(db_session)}
    project_names = {p.name for p in project_service.list_projects(db_session)}
    assert "Brand New Client" not in client_names
    assert "Brand New Project" not in project_names
    # The pre-existing, already-committed data must survive the rollback.
    assert "Existing Client" in client_names
    assert "Existing Project" in project_names

    document = get_imported_document(db_session, document.id)
    assert document.review_status == ImportReviewStatus.NEEDS_REVIEW
    assert document.resulting_client_id is None
    assert document.resulting_project_id is None
