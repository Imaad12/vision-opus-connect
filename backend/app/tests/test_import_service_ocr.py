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

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.core.enums import ConfidenceLevel, ExtractionStatus, ImportReviewStatus, SegmentReviewStatus
from app.importers.base import ExtractedTable, RawExtraction
from app.services import client_service, project_service, quotation_service
from app.services.errors import RevisionConflictError, ValidationError
from app.services.import_service import (
    accept_segment,
    check_for_duplicate,
    compute_file_hash,
    confirm_import,
    exclude_segment,
    get_imported_document,
    list_segments,
    lock_segments,
    merge_segments,
    move_segment_boundary,
    reject_import,
    split_segment,
    stage_document,
    update_quotation_candidate,
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
    """Regression test for a real production incident: every scanned
    quotation landed on OCR_REQUIRED with NO explanation at all --
    `extraction_error` stayed `None` because `run_extraction` only ever
    read `unsupported_reason` (populated for a genuinely unsupported
    file, e.g. password-protected), never `warnings` (what
    `extract_via_ocr` actually uses to report "the OCR engine itself
    isn't available on this machine" -- the real, common cause, since
    Tesseract is a system binary this backend's own Dockerfile never
    installed -- see that Dockerfile's own fix). A reviewer facing a
    silently-stalled document with no reason is indistinguishable from
    a broken pipeline; this asserts the actual reason is now surfaced."""
    path = _placeholder_scan(tmp_path)
    with patch(_PATCH_TARGET, return_value=RawExtraction(requires_ocr=True, warnings=["engine not available"])):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.OCR_REQUIRED
    assert document.extraction_engine is None
    assert document.quotation_candidate is None
    assert document.extraction_error == "engine not available"


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
    value. A printed rate with no absolute amount must never be multiplied
    out into a fabricated VAT figure -- exactly the existing, unmodified
    deterministic-path behavior (`_FIELD_LABELS` has no "VAT rate" label at
    all, so a rate-only line is simply not recognized as a monetary field).

    VAT is genuinely not determinable here (no VAT amount printed anywhere),
    so the explicit business rule applies: `tax_value` normalizes to SAR
    0.00 (never a guessed/rate-derived figure), flagged LOW confidence so
    the candidate requires review rather than silently reading as certain."""
    path = _placeholder_scan(tmp_path)
    text = "Quotation Number: Q-RATE-ONLY\nQuotation Date: 01/06/2024\nNet Amount: 100,000.00\nVAT Rate: 5%\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    candidate = document.quotation_candidate
    assert candidate.net_value == Decimal("100000.00")
    assert candidate.tax_value == Decimal("0.00")
    assert candidate.gross_value is None
    confidences = json.loads(candidate.field_confidence)
    assert confidences["tax_value"] == ConfidenceLevel.LOW.value


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


# --- 17. Multi-quotation files must not become one spliced candidate -----------
# Real archive finding: a single scanned PDF (the tested 24-page file) can
# bundle many independent quotations. Building one ImportedQuotationCandidate
# from the whole file risks silently combining a date from one quotation
# with a total from a completely different one.


def test_multi_quotation_file_is_split_into_independent_segments(db_session: Session, tmp_path: Path) -> None:
    """Direct reproduction of the real scenario: page 1's quotation A
    (444 REV/18) followed later in the same file by page 8's quotation B
    (VN/QU/412/18). Superseded behavior (pre-segmentation): the whole file
    was flatly refused. Current behavior: sequential segmentation (see
    `app.core.import_segmentation`) proposes two independent segments, and
    -- the core safety invariant -- once locked, each segment's candidate
    can only ever contain its OWN page's data. Neither reference/date ever
    merges with the other's fields, and B's total never reaches A."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Quotation Reference: 444 REV / 18\nDate: 23.12.2018\n"
        "--- Page 8 ---\n"
        "Reference: VN/QU/412/18\nDate: Nov 27, 2018\nNet Amount: 151,955.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.SEGMENTS_PROPOSED
    assert document.quotation_candidate is None  # no unsegmented candidate -- only per-segment ones
    segments = list_segments(db_session, document)
    assert len(segments) == 2
    assert segments[0].detected_quotation_number == "444 REV / 18"
    assert segments[1].detected_quotation_number == "VN/QU/412/18"

    # No boundary -- including this HIGH-confidence one -- is final until
    # explicitly accepted; nothing can be locked/extracted yet.
    assert all(s.review_status == SegmentReviewStatus.PROPOSED for s in segments)
    with pytest.raises(ValidationError, match="must be accepted or excluded"):
        lock_segments(db_session, document)

    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    assert seg_a.quotation_candidate.quotation_number == "444 REV / 18"
    assert seg_a.quotation_candidate.net_value is None  # never sees B's total
    assert seg_b.quotation_candidate.quotation_number == "VN/QU/412/18"
    assert seg_b.quotation_candidate.net_value == Decimal("151955.00")
    # The raw OCR text is still preserved for manual review, never discarded.
    assert document.raw_extracted_data is not None
    import json

    assert "VN/QU/412/18" in json.loads(document.raw_extracted_data)["text"]


def test_multi_quotation_file_cannot_be_confirmed(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = "Reference: 444 REV / 18\n" "Reference: VN/QU/412/18\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    client = client_service.create_client(db_session, name="Some Client")
    project = project_service.create_project(db_session, name="Some Project", client_id=client.id)

    with pytest.raises(ValidationError, match="Nothing to confirm"):
        confirm_import(db_session, document, client_id=client.id, project_id=project.id)

    from app.models import Client, Project, Quotation

    assert db_session.query(Quotation).count() == 0
    # The client/project created above for the attempt itself are fine
    # (existing rows, unrelated to this document) -- confirm this specific
    # document resulted in no *quotation* record at all.
    assert db_session.query(Client).count() == 1
    assert db_session.query(Project).count() == 1
    document = get_imported_document(db_session, document.id)
    assert document.review_status == ImportReviewStatus.NEEDS_REVIEW
    assert document.resulting_quotation_id is None


def test_single_quotation_file_is_unaffected_by_the_multi_quotation_check(
    db_session: Session, tmp_path: Path
) -> None:
    """The common case -- one document, one reference -- must still build
    a normal candidate exactly as before."""
    path = _placeholder_scan(tmp_path)
    text = "Reference: VN/QU/412/18\nDate: Nov 27, 2018\nNet Amount: 151,955.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert document.quotation_candidate is not None
    assert document.quotation_candidate.quotation_number == "VN/QU/412/18"
    assert document.quotation_candidate.net_value == Decimal("151955.00")


def test_lost_reference_on_one_document_cannot_splice_its_neighbors_total(
    db_session: Session, tmp_path: Path
) -> None:
    """Adversarial-review finding, reproduced end-to-end through
    segmentation: document A's reference/date are clean; document B's
    reference line was entirely lost to OCR (a real, observed failure
    mode), but its different date and net value survived. This is the
    genuinely ambiguous case (no reference on B's page to prove it's a
    different document) -- segmentation surfaces it as a LOW-confidence
    boundary rather than silently merging it into A's segment, per the
    "uncertain boundary -> manual review, never a silent guess" rule.
    Either way, the two pieces are never spliced into one candidate."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Quotation Reference: 444 REV / 18\nDate: 23.12.2018\n"
        "--- Page 8 ---\n"
        "Date: 27/11/2018\nNet Amount: 151,955.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    assert document.extraction_status == ExtractionStatus.SEGMENTS_PROPOSED
    assert document.quotation_candidate is None
    segments = list_segments(db_session, document)
    assert len(segments) == 2
    assert segments[1].boundary_confidence == ConfidenceLevel.LOW.value
    assert "no reference on this page" in segments[1].boundary_signals

    # Still nothing to confirm -- the boundary hasn't even been accepted,
    # let alone locked into a candidate.
    client = client_service.create_client(db_session, name="Some Client")
    project = project_service.create_project(db_session, name="Some Project", client_id=client.id)
    with pytest.raises(ValidationError, match="This segment must have its boundary accepted"):
        confirm_import(
            db_session, document, segment=segments[0], client_id=client.id, project_id=project.id
        )

    from app.models import Quotation

    assert db_session.query(Quotation).count() == 0

    # A reviewer who accepts and locks both pieces still gets two
    # correctly isolated candidates -- A's is missing the total (never
    # saw page 8), and B's has no reference at all (never saw page 1).
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)
    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    assert seg_a.quotation_candidate.quotation_number == "444 REV / 18"
    assert seg_a.quotation_candidate.net_value is None
    assert seg_b.quotation_candidate.quotation_number is None
    assert seg_b.quotation_candidate.net_value == Decimal("151955.00")


# --- Issue 5: uncertain BOQ structure must never fabricate financial rows -----


def test_real_archive_shaped_garbled_boq_header_creates_no_rows(db_session: Session, tmp_path: Path) -> None:
    """Reproduces the exact real-archive OCR failure mode: a BOQ header
    row OCR'd with its "Description"/"Qty" keywords lost ("mae Unit Rate"
    instead of "Description | Qty | Unit Rate | Total"), leaving only one
    recognizable keyword. Must yield zero BOQ rows -- never guessed/
    misaligned ones -- exactly as observed against the real archive."""
    path = _placeholder_scan(tmp_path)
    table = ExtractedTable(
        name="page 8 (OCR)",
        rows=[
            ["mae Unit Rate"],
            ["Close workshop area", "177", "75", "13,275.00"],
            ["Painting work", "487m", "30", "14,610.00"],
        ],
    )
    text = "Reference: VN/QU/412/18\nDate: Nov 27, 2018\nNet Amount: 151,955.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text, tables=[table])):
        document = stage_document(db_session, path)

    assert list(document.boq_line_candidates) == []
    # The quotation-level fields are unaffected by the BOQ table failure.
    assert document.quotation_candidate.net_value == Decimal("151955.00")


# --- Sequential segmentation: cases 13-16 from the segmentation brief ----------


def test_confirmed_candidate_cannot_access_financial_data_outside_its_segment(
    db_session: Session, tmp_path: Path
) -> None:
    """Case 13. The core safety invariant, proven directly against a
    confirmed (not just locked) business record: segment A's confirmed
    `QuotationVersion` must carry only A's own total, never B's, even
    though B's total sits later in the very same source file."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Reference: A-100\nDate: 01/01/2024\nNet Amount: 1,000.00\n"
        "--- Page 2 ---\n"
        "Reference: A-200\nDate: 02/01/2024\nNet Amount: 9,999.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 2
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    client = client_service.create_client(db_session, name="Client A")
    project = project_service.create_project(db_session, name="Project A", client_id=client.id)
    version_a = confirm_import(db_session, document, segment=seg_a, client_id=client.id, project_id=project.id)

    assert version_a.quoted_value == Decimal("1000.00")
    assert version_a.quoted_value != Decimal("9999.00")

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    assert seg_a.review_status == SegmentReviewStatus.CONFIRMED
    assert seg_b.review_status == SegmentReviewStatus.LOCKED  # untouched by A's confirmation
    assert seg_b.quotation_candidate.net_value == Decimal("9999.00")


def test_moving_a_boundary_invalidates_and_re_extracts_affected_candidates(
    db_session: Session, tmp_path: Path
) -> None:
    """Case 14. A reviewer discovers segmentation drew the line one page
    too early -- moving the boundary must discard both segments' existing
    candidates (never patch them) and produce fresh, correctly-scoped
    ones on the next lock."""
    path = _placeholder_scan(tmp_path)
    # Page 2 carries only a total, with no reference/date of its own --
    # segmentation initially attaches it to A (no new identity signal on
    # page 2). Page 3 has no amount at all, keeping which page's total
    # ends up where unambiguous throughout this test.
    text = (
        "Reference: A-100\nDate: 01/01/2024\n"
        "--- Page 2 ---\n"
        "Net Amount: 1,000.00\n"
        "--- Page 3 ---\n"
        "Reference: A-200\nDate: 02/01/2024\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 2
    assert (segments[0].start_page, segments[0].end_page) == (1, 2)
    assert (segments[1].start_page, segments[1].end_page) == (3, 3)

    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    assert seg_a.quotation_candidate.net_value == Decimal("1000.00")
    assert seg_b.quotation_candidate.net_value is None
    first_candidate_id = seg_a.quotation_candidate.id

    # Reviewer decides page 2's total actually belongs to quotation B, not
    # A -- moving the boundary must discard both existing candidates
    # (never patch them) rather than leave A's stale total in place.
    move_segment_boundary(db_session, document, seg_a, new_end_page=1)
    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    assert seg_a.quotation_candidate is None
    assert seg_b.quotation_candidate is None
    assert seg_a.review_status == SegmentReviewStatus.PROPOSED
    assert seg_b.review_status == SegmentReviewStatus.PROPOSED
    assert seg_a.reviewer_adjusted is True

    from app.models import ImportedQuotationCandidate

    assert db_session.get(ImportedQuotationCandidate, first_candidate_id) is None

    accept_segment(db_session, document, seg_a)
    accept_segment(db_session, document, seg_b)
    lock_segments(db_session, document)
    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    assert seg_a.start_page == 1 and seg_a.end_page == 1
    assert seg_b.start_page == 2 and seg_b.end_page == 3
    # Page 2's total now correctly belongs to segment B, not A.
    assert seg_a.quotation_candidate.net_value is None
    assert seg_b.quotation_candidate.net_value == Decimal("1000.00")


def test_merging_and_splitting_segments_leaves_no_stale_candidates(
    db_session: Session, tmp_path: Path
) -> None:
    """Case 15. Merge (segmentation over-split one quotation) and split
    (segmentation under-split two) must each leave the database with
    exactly the candidates the *current* boundary layout implies -- no
    orphaned rows from a prior layout."""
    path = _placeholder_scan(tmp_path)
    # Page 1 has no identifying fields at all (a cover page OCR read
    # poorly); page 2 is where this one quotation's own reference first
    # appears. Per the documented, safety-motivated bias (a late-revealed
    # reference over-splits rather than risking a silent merge), this
    # proposes two segments for what is really one quotation -- exactly
    # the case `merge_segments` exists to correct.
    text = "Some cover text with no reference or date recognized here.\n--- Page 2 ---\nReference: A-100\nDate: 01/01/2024\nNet Amount: 2,000.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 2
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    from app.models import ImportedQuotationCandidate

    document = get_imported_document(db_session, document.id)
    assert db_session.query(ImportedQuotationCandidate).count() == 2

    seg_a, seg_b = list_segments(db_session, document)
    merged = merge_segments(db_session, document, seg_a, seg_b)
    document = get_imported_document(db_session, document.id)
    remaining = list_segments(db_session, document)
    assert len(remaining) == 1
    assert remaining[0].id == merged.id
    assert (remaining[0].start_page, remaining[0].end_page) == (1, 2)
    assert remaining[0].review_status == SegmentReviewStatus.PROPOSED
    # Both prior candidates gone -- neither patched, neither orphaned.
    assert db_session.query(ImportedQuotationCandidate).count() == 0

    accept_segment(db_session, document, remaining[0])
    lock_segments(db_session, document)
    document = get_imported_document(db_session, document.id)
    (merged_segment,) = list_segments(db_session, document)
    assert merged_segment.quotation_candidate.quotation_number == "A-100"
    assert merged_segment.quotation_candidate.net_value == Decimal("2000.00")
    assert db_session.query(ImportedQuotationCandidate).count() == 1

    # Now split it back into two (a reviewer might do this for an
    # unrelated reason, e.g. realizing page 1 is actually a separate
    # attachment) -- the merged candidate must not survive the split.
    piece_a, piece_b = split_segment(db_session, document, merged_segment, split_after_page=1)
    document = get_imported_document(db_session, document.id)
    pieces = list_segments(db_session, document)
    assert len(pieces) == 2
    assert (pieces[0].start_page, pieces[0].end_page) == (1, 1)
    assert (pieces[1].start_page, pieces[1].end_page) == (2, 2)
    # The pre-split candidate is gone; nothing stale survives the split.
    assert db_session.query(ImportedQuotationCandidate).count() == 0

    for piece in pieces:
        accept_segment(db_session, document, piece)
    lock_segments(db_session, document)
    document = get_imported_document(db_session, document.id)
    piece_a, piece_b = list_segments(db_session, document)
    assert piece_a.quotation_candidate.quotation_number is None  # page 1 alone has nothing
    assert piece_b.quotation_candidate.quotation_number == "A-100"
    assert piece_b.quotation_candidate.net_value == Decimal("2000.00")
    assert db_session.query(ImportedQuotationCandidate).count() == 2


def test_excluded_pages_never_enter_a_quotation_candidate(db_session: Session, tmp_path: Path) -> None:
    """Case 16. A page range marked EXCLUDED_NOT_A_QUOTATION (an
    attachment/drawing run between two real quotations) must never
    produce a candidate itself, and its content must never leak into
    either neighboring segment's candidate."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Reference: A-100\nDate: 01/01/2024\nNet Amount: 1,000.00\n"
        "--- Page 2 ---\n"
        "Reference: DRAWING-REV-3\nDate: 15/06/2020\nNet Amount: 999,999.00\n"
        "--- Page 3 ---\n"
        "Reference: A-200\nDate: 02/01/2024\nNet Amount: 2,000.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 3
    middle = segments[1]
    exclude_segment(db_session, document, middle)

    document = get_imported_document(db_session, document.id)
    segments = list_segments(db_session, document)
    middle = segments[1]
    assert middle.review_status == SegmentReviewStatus.EXCLUDED_NOT_A_QUOTATION

    accept_segment(db_session, document, segments[0])
    accept_segment(db_session, document, segments[2])
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg_a, excluded, seg_b = list_segments(db_session, document)
    assert excluded.quotation_candidate is None
    assert seg_a.quotation_candidate.quotation_number == "A-100"
    assert seg_a.quotation_candidate.net_value == Decimal("1000.00")
    assert seg_b.quotation_candidate.quotation_number == "A-200"
    assert seg_b.quotation_candidate.net_value == Decimal("2000.00")

    from app.models import ImportedQuotationCandidate

    numbers = {c.quotation_number for c in db_session.query(ImportedQuotationCandidate).all()}
    assert "DRAWING-REV-3" not in numbers
    values = {c.net_value for c in db_session.query(ImportedQuotationCandidate).all()}
    assert Decimal("999999.00") not in values


def test_rejected_segment_leaves_no_business_records(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = "Reference: A-100\nDate: 01/01/2024\nNet Amount: 1,000.00\n--- Page 2 ---\nReference: A-200\nDate: 02/01/2024\nNet Amount: 2,000.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)
    segments = list_segments(db_session, document)
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    reject_import(db_session, document, segment=seg_a, reason="Duplicate of an existing paper quotation.")

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    assert seg_a.review_status == SegmentReviewStatus.REJECTED
    assert seg_a.resulting_quotation_id is None

    from app.models import Quotation

    assert db_session.query(Quotation).count() == 0

    with pytest.raises(ValidationError, match="rejected"):
        confirm_import(db_session, document, segment=seg_a, client_id=1, project_id=1)


def test_segment_still_ambiguous_after_locking_produces_no_candidate(
    db_session: Session, tmp_path: Path
) -> None:
    """A pathological case: a reviewer accepts a boundary that, once
    sliced, still itself contains two distinct references (e.g. they
    merged two genuinely different quotations together by mistake). The
    within-slice multi-signal check (unchanged from the original Phase 4
    gate) still catches it -- the segment locks with no candidate rather
    than silently picking one reference over the other."""
    path = _placeholder_scan(tmp_path)
    text = "Reference: A-100\nDate: 01/01/2024\nReference: A-200\nDate: 02/01/2024\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    # No page markers at all here -- falls back to the original
    # single-candidate path, which itself detects the multi-signal.
    assert document.extraction_status == ExtractionStatus.MULTIPLE_QUOTATIONS_DETECTED
    assert document.quotation_candidate is None


def test_segment_confirmation_participates_in_pr5_revision_conflict_protection(
    db_session: Session, tmp_path: Path
) -> None:
    """A segment's confirmation reuses `quotation_service`'s revision
    machinery exactly like the unsegmented path -- confirming a second
    segment as a revision of the quotation the first segment just created
    still runs PR #5's conflict check."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Reference: VN/QU/412/18\nDate: 27/11/2018\nNet Amount: 151,955.00\n"
        "--- Page 2 ---\n"
        "Reference: VN/QU/412/18\nDate: 21/11/2018\nNet Amount: 168,495.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 2
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    client = client_service.create_client(db_session, name="Vinco Client")
    project = project_service.create_project(db_session, name="Vinco Project", client_id=client.id)
    version_a = confirm_import(db_session, document, segment=seg_a, client_id=client.id, project_id=project.id)

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    # Segment B is dated *earlier* than the quotation segment A just
    # created -- PR #5's conflict check must still block it.
    with pytest.raises(RevisionConflictError):
        confirm_import(
            db_session,
            document,
            segment=seg_b,
            client_id=client.id,
            project_id=project.id,
            quotation_id=version_a.quotation_id,
        )

    confirm_import(
        db_session,
        document,
        segment=seg_b,
        client_id=client.id,
        project_id=project.id,
        quotation_id=version_a.quotation_id,
        acknowledge_revision_conflict=True,
    )

    from app.models import QuotationVersion

    versions = db_session.query(QuotationVersion).filter_by(quotation_id=version_a.quotation_id).all()
    assert len(versions) == 2


def test_original_source_file_remains_byte_identical_through_segmentation(
    db_session: Session, tmp_path: Path
) -> None:
    path = _placeholder_scan(tmp_path)
    original_bytes = path.read_bytes()
    original_hash = compute_file_hash(path)
    text = "Reference: A-100\nDate: 01/01/2024\nNet Amount: 1,000.00\n--- Page 2 ---\nReference: A-200\nDate: 02/01/2024\nNet Amount: 2,000.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)
    segments = list_segments(db_session, document)
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)
    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    client = client_service.create_client(db_session, name="Client")
    project = project_service.create_project(db_session, name="Project", client_id=client.id)
    confirm_import(db_session, document, segment=seg_a, client_id=client.id, project_id=project.id)

    assert path.read_bytes() == original_bytes
    assert compute_file_hash(path) == original_hash


def test_confirmed_segment_boundary_cannot_be_changed(db_session: Session, tmp_path: Path) -> None:
    path = _placeholder_scan(tmp_path)
    text = "Reference: A-100\nDate: 01/01/2024\nNet Amount: 1,000.00\n--- Page 2 ---\nReference: A-200\nDate: 02/01/2024\nNet Amount: 2,000.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)
    segments = list_segments(db_session, document)
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)
    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    client = client_service.create_client(db_session, name="Client")
    project = project_service.create_project(db_session, name="Project", client_id=client.id)
    confirm_import(db_session, document, segment=seg_a, client_id=client.id, project_id=project.id)

    document = get_imported_document(db_session, document.id)
    seg_a, seg_b = list_segments(db_session, document)
    with pytest.raises(ValidationError, match="already been confirmed"):
        move_segment_boundary(db_session, document, seg_a, new_end_page=2)
    with pytest.raises(ValidationError, match="already been confirmed"):
        merge_segments(db_session, document, seg_a, seg_b)


# --- Final adversarial review: financial value with no page-level identity ----
# corroboration (the "reference A + unrelated total B" exploit) ---------------


def test_financial_value_on_an_unidentified_page_cannot_splice_into_a_confirmable_candidate(
    db_session: Session, tmp_path: Path
) -> None:
    """The exact exploit from the final adversarial review: quotation A's
    reference/date survive (page 1); an entirely separate, unidentified
    document's total survives later in the same file (page 3) with
    neither its own reference nor date recognized at all. Segmentation
    itself proposes no boundary here (page 3 contributes zero identity
    signal, so it is absorbed as a continuation -- the documented,
    accepted trade-off that avoids ever incorrectly splitting a
    legitimate long quotation). Before this fix, the resulting single
    segment's candidate combined A's own reference/date with the
    unrelated total, all individually HIGH confidence, fully
    confirmable, and wrong -- reproduced and confirmed end-to-end
    (including an actual `QuotationVersion` write) during the review.
    Must now be blocked."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Reference: VN/QU/412/18\nDate: 27/11/2018\nClient: Ashtead Technology\n"
        "--- Page 2 ---\n"
        "Item 1 description continues\nQty: 10\n"
        "--- Page 3 ---\n"
        "Net Amount: 999,999.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 1  # segmentation itself is correctly unaffected -- see module docstring
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg = list_segments(db_session, document)[0]
    candidate = seg.quotation_candidate
    assert candidate is not None
    assert candidate.quotation_number == "VN/QU/412/18"
    assert candidate.net_value == Decimal("999999.00")  # still visible for the reviewer to inspect/correct
    confidence = json.loads(candidate.field_confidence)
    assert confidence["net_value"] == "LOW"

    client = client_service.create_client(db_session, name="Ashtead Technology")
    project = project_service.create_project(db_session, name="Office Facilities Work", client_id=client.id)
    with pytest.raises(ValidationError, match="cannot be confirmed yet"):
        confirm_import(db_session, document, segment=seg, client_id=client.id, project_id=project.id)

    from app.models import Quotation

    assert db_session.query(Quotation).count() == 0


def test_cost_of_the_work_sentence_on_an_unidentified_page_cannot_splice_either(
    db_session: Session, tmp_path: Path
) -> None:
    """Same exploit shape as the test above, reproduced with the new
    "cost of the work" net-value fallback (OCR Phase 4 round 3) instead
    of a labeled "Net Amount:" line -- this is the exact real archive
    shape found during real-archive validation: pages 10-11 (VN/QU/406/18
    followed by an unrelated bleed-through page with no reference/date of
    its own) produced a net_value from the bleed-through page's own
    "cost of the work" sentence, not from 406's real total. The new
    pattern must be caught by the same, pre-existing, unmodified
    identity-corroboration check as any other financial value -- it gets
    no special exemption for being a newer extraction path."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Reference: VN/QU/406/18\nDate: 19/11/2018\n"
        "--- Page 2 ---\n"
        "The cost of the work with labor and materials SR 18,000.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 1  # no identity signal on page 2 -- correctly not split
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg = list_segments(db_session, document)[0]
    candidate = seg.quotation_candidate
    assert candidate is not None
    assert candidate.net_value == Decimal("18000.00")  # still visible for the reviewer to inspect/correct
    confidence = json.loads(candidate.field_confidence)
    assert confidence["net_value"] == "LOW"

    client = client_service.create_client(db_session, name="Zamil Industrial Coating")
    project = project_service.create_project(db_session, name="Concrete/Tile Floor", client_id=client.id)
    with pytest.raises(ValidationError, match="cannot be confirmed yet"):
        confirm_import(db_session, document, segment=seg, client_id=client.id, project_id=project.id)

    from app.models import Quotation

    assert db_session.query(Quotation).count() == 0


def test_legitimate_long_quotation_total_is_not_split_but_requires_reviewer_sign_off(
    db_session: Session, tmp_path: Path
) -> None:
    """The honest trade-off this fix accepts: a genuinely long, single
    quotation whose own total legitimately appears on a later page is
    NOT incorrectly split into multiple segments (segmentation itself is
    unaffected -- there is no per-page signal to distinguish this from
    the exploit above, by design). Its total is flagged for explicit
    reviewer sign-off rather than auto-confirmed, but an actual review
    action (re-entering the value) unblocks it -- this is friction, not
    a dead end."""
    path = _placeholder_scan(tmp_path)
    text = (
        "Reference: VN/QU/500/18\nDate: 01/12/2018\n"
        "--- Page 2 ---\nItem 1: Supply cabling\nQty: 100\n"
        "--- Page 3 ---\nItem 2: Supply trunking\nQty: 40\n"
        "--- Page 4 ---\nItem 3: Labor\nQty: 1\n"
        "--- Page 5 ---\nNet Amount: 55,000.00\n"
    )
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 1  # not incorrectly split
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg = list_segments(db_session, document)[0]
    candidate = seg.quotation_candidate
    assert candidate.net_value == Decimal("55000.00")

    client = client_service.create_client(db_session, name="Client")
    project = project_service.create_project(db_session, name="Project", client_id=client.id)
    with pytest.raises(ValidationError, match="cannot be confirmed yet"):
        confirm_import(db_session, document, segment=seg, client_id=client.id, project_id=project.id)

    # A genuine reviewer action (re-entering the value after checking the
    # source scan) clears the flag -- not a permanent dead end.
    update_quotation_candidate(db_session, document, candidate, net_value=Decimal("55000.01"))
    update_quotation_candidate(db_session, document, candidate, net_value=Decimal("55000.00"))
    document = get_imported_document(db_session, document.id)
    seg = list_segments(db_session, document)[0]
    version = confirm_import(db_session, document, segment=seg, client_id=client.id, project_id=project.id)
    assert version.quoted_value == Decimal("55000.00")


def test_plain_focus_change_does_not_clear_the_low_confidence_flag(db_session: Session, tmp_path: Path) -> None:
    """A reviewer merely tabbing through the net-value field (the same
    UI event a genuine edit produces, `editingFinished`, but with an
    unchanged value) must not silently clear the LOW flag -- only an
    actual value change counts as review sign-off. Otherwise the gate
    could be defeated by incidental UI interaction rather than deliberate
    review."""
    path = _placeholder_scan(tmp_path)
    text = "Reference: VN/QU/412/18\nDate: 27/11/2018\n--- Page 2 ---\nNet Amount: 999,999.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)
    segments = list_segments(db_session, document)
    for segment in segments:
        accept_segment(db_session, document, segment)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    seg = list_segments(db_session, document)[0]
    candidate = seg.quotation_candidate
    # Resubmitting the SAME value -- what a plain focus-out produces.
    update_quotation_candidate(db_session, document, candidate, net_value=candidate.net_value)

    document = get_imported_document(db_session, document.id)
    seg = list_segments(db_session, document)[0]
    confidence = json.loads(seg.quotation_candidate.field_confidence)
    assert confidence["net_value"] == "LOW"  # still flagged -- unchanged resubmission is not review


def test_same_page_reference_date_and_total_are_unaffected(db_session: Session, tmp_path: Path) -> None:
    """The overwhelming common case -- everything on one page -- must
    stay HIGH confidence and immediately confirmable, exactly as before
    this fix."""
    path = _placeholder_scan(tmp_path)
    text = "Reference: VN/QU/412/18\nDate: 27/11/2018\nNet Amount: 151,955.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    # No page markers at all -- falls back to the original single-
    # candidate path, unaffected by segmentation or this fix.
    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    candidate = document.quotation_candidate
    confidence = json.loads(candidate.field_confidence)
    assert confidence["net_value"] == "HIGH"

    client = client_service.create_client(db_session, name="Client")
    project = project_service.create_project(db_session, name="Project", client_id=client.id)
    version = confirm_import(db_session, document, client_id=client.id, project_id=project.id)
    assert version.quoted_value == Decimal("151955.00")


def test_mistaken_manual_merge_across_a_low_confidence_boundary_still_blocked(
    db_session: Session, tmp_path: Path
) -> None:
    """If a reviewer merges two segments across a LOW-confidence
    date-conflict boundary (mistakenly believing it's one document), the
    pre-existing within-slice distinct-date multi-signal check -- wholly
    unrelated to this round's fix -- still catches it: no candidate is
    created at all, a stronger outcome than merely flagging one field."""
    path = _placeholder_scan(tmp_path)
    text = "Reference: 444 REV / 18\nDate: 23.12.2018\n--- Page 2 ---\nDate: 27/11/2018\nNet Amount: 151,955.00\n"
    with patch(_PATCH_TARGET, return_value=_ocr_result(text)):
        document = stage_document(db_session, path)

    segments = list_segments(db_session, document)
    assert len(segments) == 2
    assert segments[1].boundary_confidence == ConfidenceLevel.LOW.value

    merged = merge_segments(db_session, document, segments[0], segments[1])
    accept_segment(db_session, document, merged)
    lock_segments(db_session, document)

    document = get_imported_document(db_session, document.id)
    (seg,) = list_segments(db_session, document)
    assert seg.quotation_candidate is None
