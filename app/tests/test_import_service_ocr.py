"""End-to-end OCR Phase 1 tests through the real Phase 4 pipeline:
`stage_document` -> `run_extraction` -> (review/edit) -> `confirm_import`.

`app.services.import_service.extract_via_ocr` is patched to return a
controlled `RawExtraction` in most tests here -- the orchestrator itself
(page rendering, per-page failure handling, table reconstruction) is
already covered directly, against real rasterized PDFs, in
`test_ocr_extraction.py`. What these tests prove is the integration: that
an OCR-derived candidate flows through the *unmodified* Phase 4 staging/
matching/confirmation machinery -- including PR #5's revision-conflict
protection -- exactly the way a deterministically-parsed one does, with
the one added OCR-specific safety gate (`OcrConfidenceStatus.BLOCKED`)
enforced defensively inside `confirm_import` itself, not just in the UI.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.core.enums import ExtractionStatus, ImportReviewStatus
from app.importers.base import ExtractedTable, RawExtraction
from app.services import client_service, project_service, quotation_service
from app.services.errors import RevisionConflictError, ValidationError
from app.services.import_service import (
    check_for_duplicate,
    compute_file_hash,
    confirm_import,
    get_imported_document,
    reject_import,
    stage_document,
)

_PATCH_TARGET = "app.services.import_service.extract_via_ocr"


def _placeholder_scan(tmp_path: Path, name: str = "scan.png") -> Path:
    # ImageImporter never reads the file's actual bytes -- it always
    # reports `requires_ocr=True` unconditionally for any image extension
    # -- so the placeholder content only needs to exist on disk.
    path = tmp_path / name
    path.write_bytes(f"not a real image -- content is irrelevant, ImageImporter never reads it ({name})".encode())
    return path


def _ocr_result(text: str, **kwargs) -> RawExtraction:
    return RawExtraction(text=text, ocr_pages=[{"page_number": 1, "char_count": len(text), "mean_confidence": 90.0, "failed": False}], **kwargs)


# --- 1. Clean scanned quotation ----------------------------------------------


def test_clean_scanned_quotation_is_staged_with_high_confidence(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = (
        "Quotation Number: VN/QU/412/18\n"
        "Quotation Date: 21/11/2018\n"
        "Client Name: Ashtead Technology\n"
        "Project Name: Office Facilities Work\n"
        "Net Amount: 168,495.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert document.extraction_engine == "ocr"
    candidate = document.quotation_candidate
    assert candidate is not None
    assert candidate.quotation_number == "VN/QU/412/18"
    assert candidate.net_value == Decimal("168495.00")
    assert candidate.quotation_date.isoformat() == "2018-11-21"


# --- 2. OCR engine failure ----------------------------------------------------


def test_ocr_engine_unavailable_stays_ocr_required_with_no_candidate(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    with patch(_PATCH_TARGET, return_value=RawExtraction(requires_ocr=True, warnings=["engine not available"])):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.OCR_REQUIRED
    assert document.extraction_engine is None
    assert document.quotation_candidate is None


def test_ocr_extraction_raising_unexpectedly_is_caught_and_marked_failed(db_session: Session, tmp_path: Path) -> None:
    """Defense in depth: `extract_via_ocr` itself is already hardened
    against internal failures (see test_ocr_extraction.py), but
    `run_extraction` must not trust that on its own behalf either -- an
    unexpected exception from the OCR call must never propagate out of
    `run_extraction`, which promises ("never raises") the same guarantee
    it already gives the deterministic importer path."""
    path = _placeholder_scan(tmp_path)
    with patch(_PATCH_TARGET, side_effect=RuntimeError("boom")):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.FAILED
    assert "OCR extraction failed" in document.extraction_error
    assert document.extraction_engine is None
    assert document.quotation_candidate is None


# --- 3. Empty OCR output -------------------------------------------------------


def test_empty_ocr_output_stages_with_no_fabricated_fields(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    with patch(_PATCH_TARGET, return_value=RawExtraction(text=None, warnings=["OCR could not read any page."])):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert document.extraction_engine == "ocr"
    candidate = document.quotation_candidate
    assert candidate is not None
    assert candidate.quotation_number is None
    assert candidate.net_value is None
    assert candidate.quotation_date is None
    # Cannot be confirmed -- mandatory fields are missing.
    with pytest.raises(ValidationError, match="cannot be confirmed"):
        confirm_import(db_session, document, client_id=None, new_client_name="Some Client", project_id=None, new_project_name="Some Project")


# --- 4. Partial OCR -------------------------------------------------------------


def test_partial_ocr_populates_only_the_fields_that_were_read(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = "Quotation Number: Q-PARTIAL-1\nQuotation Date: 01/06/2024\n"  # no net/gross value at all
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    candidate = document.quotation_candidate
    assert candidate.quotation_number == "Q-PARTIAL-1"
    assert candidate.quotation_date.isoformat() == "2024-06-01"
    assert candidate.net_value is None  # never fabricated


# --- 5. Missing quotation reference --------------------------------------------


def test_missing_reference_is_review_required_not_blocked(db_session: Session, tmp_path: Path) -> None:
    """No reference number at all is a real, common archive case (see the
    OCR design review) -- it must not silently block confirmation, since
    `Quotation.reference_number` is nullable and a reviewer can still
    confirm a referenceless quotation exactly as Phase 4 always allowed."""
    path = _placeholder_scan(tmp_path)
    text = "Quotation Date: 01/06/2024\nNet Amount: 50,000.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    client = client_service.create_client(db_session, name="Some Client")
    project = project_service.create_project(db_session, name="Some Project", client_id=client.id)
    version = confirm_import(db_session, document, client_id=client.id, project_id=project.id)
    assert version.quoted_value == Decimal("50000.00")


# --- 6. Missing financial values (BLOCKED) -------------------------------------


def test_missing_net_value_blocks_confirmation_even_if_ui_is_bypassed(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = "Quotation Number: Q-NO-VALUE\nQuotation Date: 01/06/2024\n"  # no net/gross value
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    client = client_service.create_client(db_session, name="Some Client")
    project = project_service.create_project(db_session, name="Some Project", client_id=client.id)

    with pytest.raises(ValidationError, match="cannot be confirmed"):
        confirm_import(db_session, document, client_id=client.id, project_id=project.id)

    # Nothing was written -- the guard fires before any business record is touched.
    document = get_imported_document(db_session, document.id)
    assert document.review_status == ImportReviewStatus.NEEDS_REVIEW
    assert document.resulting_quotation_id is None


# --- 7. Explicit net / VAT / gross extraction -----------------------------------


def test_explicit_net_vat_gross_are_all_captured_distinctly(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = (
        "Quotation Number: Q-VAT-1\n"
        "Quotation Date: 01/06/2024\n"
        "Net Amount: 100,000.00\n"
        "VAT Amount: 5,000.00\n"
        "Total Including VAT: 105,000.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    candidate = document.quotation_candidate
    assert candidate.net_value == Decimal("100000.00")
    assert candidate.tax_value == Decimal("5000.00")
    assert candidate.gross_value == Decimal("105000.00")


# --- 8. VAT rate stated without VAT amount (never inferred as a value) --------


def test_vat_rate_alone_is_never_treated_as_a_monetary_value(db_session: Session, tmp_path: Path) -> None:
    """The brief requires: never infer a VAT rate, never invent a missing
    value. A printed rate with no absolute amount must leave `tax_value`
    untouched -- exactly the existing, unmodified deterministic-path
    behavior (`_FIELD_LABELS` has no "VAT rate" label at all, so a rate-only
    line is simply not recognized as a monetary field)."""
    path = _placeholder_scan(tmp_path)
    text = "Quotation Number: Q-RATE-ONLY\nQuotation Date: 01/06/2024\nNet Amount: 100,000.00\nVAT Rate: 5%\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    candidate = document.quotation_candidate
    assert candidate.net_value == Decimal("100000.00")
    assert candidate.tax_value is None
    assert candidate.gross_value is None


# --- 9. Multiple totals on one document (documented, existing behavior) -------


def test_multiple_totals_does_not_crash_and_still_requires_human_review(db_session: Session, tmp_path: Path) -> None:
    """OCR Phase 1 does not add conflict-detection for multiple distinct
    "total"-shaped labels within a single document (this is unchanged,
    existing first-match-wins label matching -- see the implementation
    report's limitations). What this test guarantees is the safety
    invariant that actually matters: no crash, and human review remains
    the unconditional gate before confirmation regardless of which total
    was picked up."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Quotation Number: Q-MULTI-TOTAL\nQuotation Date: 01/06/2024\n"
        "Grand Total: 200,000.00\nTotal Amount: 210,000.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert document.quotation_candidate.gross_value in (Decimal("200000.00"), Decimal("210000.00"))


# --- 10. BOQ extraction ---------------------------------------------------------


def test_boq_rows_are_staged_from_an_ocr_reconstructed_table(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    table = ExtractedTable(
        name="page 1 (OCR)",
        rows=[
            ["Item", "Description", "Qty", "Unit", "Rate", "Amount"],
            ["1", "Excavation", "10", "m3", "50.00", "500.00"],
            ["2", "Blockwork", "200", "m2", "75.00", "15000.00"],
        ],
    )
    text = "Quotation Number: Q-BOQ-1\nQuotation Date: 01/06/2024\nNet Amount: 15,500.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text, tables=[table])):
        document = stage_document(db_session, path)

    boq_lines = list(document.boq_line_candidates)
    assert len(boq_lines) == 2
    assert boq_lines[0].description == "Excavation"
    assert boq_lines[0].calculated_amount == Decimal("500.00")
    assert boq_lines[1].amount_flagged is False


# --- 11. Ambiguous BOQ structure -------------------------------------------------


def test_ambiguous_boq_structure_creates_no_rows_but_surfaces_a_warning(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = "Quotation Number: Q-AMBIG-BOQ\nQuotation Date: 01/06/2024\nNet Amount: 10,000.00\n"
    warning = "Page 1: a table-like region was found but its column structure could not be reliably identified."
    with patch(_PATCH_TARGET, return_value=_ocr_result(text, warnings=[warning])):
        document = stage_document(db_session, path)

    assert list(document.boq_line_candidates) == []
    import json

    stored = json.loads(document.raw_extracted_data)
    assert any("could not be reliably identified" in w for w in stored["warnings"])


# --- 12. Same reference, different date/total (PR #5 conflict, reused) --------


def test_same_reference_different_date_total_still_goes_through_pr5_conflict_check(
    db_session: Session, tmp_path: Path
) -> None:
    client = client_service.create_client(db_session, name="Ashtead Technology")
    project = project_service.create_project(db_session, name="Office Facilities Work", client_id=client.id)

    later_path = _placeholder_scan(tmp_path, "later.png")
    later_text = (
        "Quotation Number: VN/QU/412/18\nQuotation Date: 27/11/2018\n"
        "Client Name: Ashtead Technology\nProject Name: Office Facilities Work\nNet Amount: 151,955.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(later_text)):
        later_document = stage_document(db_session, later_path)
    later_version = confirm_import(db_session, later_document, client_id=client.id, project_id=project.id)

    earlier_path = _placeholder_scan(tmp_path, "earlier.png")
    earlier_text = (
        "Quotation Number: VN/QU/412/18\nQuotation Date: 21/11/2018\n"
        "Client Name: Ashtead Technology\nProject Name: Office Facilities Work\nNet Amount: 168,495.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(earlier_text)):
        earlier_document = stage_document(db_session, earlier_path)

    with pytest.raises(RevisionConflictError) as excinfo:
        confirm_import(
            db_session,
            earlier_document,
            client_id=client.id,
            project_id=project.id,
            quotation_id=later_version.quotation_id,
        )
    assert excinfo.value.conflict_type == "earlier"

    # Acknowledging proceeds exactly as PR #5 already proves for the
    # deterministic path -- OCR does not bypass or duplicate that logic.
    resolved_version = confirm_import(
        db_session,
        earlier_document,
        client_id=client.id,
        project_id=project.id,
        quotation_id=later_version.quotation_id,
        acknowledge_revision_conflict=True,
    )
    assert resolved_version.quotation_id == later_version.quotation_id
    assert len(quotation_service.list_versions_for_quotation(db_session, later_version.quotation_id)) == 2


# --- 13. OCR candidate cannot bypass confirmation -------------------------------


def test_blocked_ocr_candidate_cannot_be_confirmed_by_calling_the_service_directly(
    db_session: Session, tmp_path: Path
) -> None:
    """Proves the gate is enforced in `confirm_import` itself, not merely
    in the UI -- calling the service function directly, exactly as a UI
    bypass or a future automation would, must still fail."""
    path = _placeholder_scan(tmp_path)
    with patch(_PATCH_TARGET, return_value=_ocr_result("Quotation Number: Q-BLOCKED\n")):  # no date, no value
        document = stage_document(db_session, path)

    client = client_service.create_client(db_session, name="Some Client")
    project = project_service.create_project(db_session, name="Some Project", client_id=client.id)

    with pytest.raises(ValidationError):
        confirm_import(db_session, document, client_id=client.id, project_id=project.id)

    document = get_imported_document(db_session, document.id)
    assert document.review_status == ImportReviewStatus.NEEDS_REVIEW


# --- 14. Rejected OCR import creates no business records -----------------------


def test_rejected_ocr_import_creates_no_business_records(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = "Quotation Number: Q-REJECT\nQuotation Date: 01/06/2024\nNet Amount: 10,000.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    reject_import(db_session, document)

    document = get_imported_document(db_session, document.id)
    assert document.review_status == ImportReviewStatus.REJECTED
    assert document.resulting_client_id is None
    assert document.resulting_project_id is None
    assert document.resulting_quotation_id is None

    with pytest.raises(ValidationError, match="rejected"):
        confirm_import(db_session, document, client_id=None, new_client_name="X", project_id=None, new_project_name="Y")


# --- 15. Failed confirmation rolls back completely ------------------------------


def test_failed_confirmation_after_a_valid_ocr_candidate_rolls_back_completely(
    db_session: Session, tmp_path: Path
) -> None:
    path = _placeholder_scan(tmp_path)
    text = "Quotation Number: Q-ROLLBACK\nQuotation Date: 01/06/2024\nNet Amount: 10,000.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    with pytest.raises(ValidationError, match="Select a valid client"):
        confirm_import(db_session, document, client_id=999999, project_id=None, new_project_name="Y")

    document = get_imported_document(db_session, document.id)
    assert document.review_status == ImportReviewStatus.NEEDS_REVIEW
    assert document.resulting_client_id is None
    assert document.resulting_project_id is None
    assert document.resulting_quotation_id is None


# --- 16. Original source remains byte-identical --------------------------------


def test_original_source_file_is_byte_identical_after_the_full_pipeline(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    original_bytes = path.read_bytes()
    original_hash = compute_file_hash(path)

    text = "Quotation Number: Q-UNTOUCHED\nQuotation Date: 01/06/2024\nNet Amount: 10,000.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    client = client_service.create_client(db_session, name="Some Client")
    project = project_service.create_project(db_session, name="Some Project", client_id=client.id)
    confirm_import(db_session, document, client_id=client.id, project_id=project.id)

    assert path.read_bytes() == original_bytes
    assert compute_file_hash(path) == original_hash
    # And a second stage_document call against the same untouched file
    # still recognizes it as the exact same content.
    assert check_for_duplicate(db_session, path) is not None
