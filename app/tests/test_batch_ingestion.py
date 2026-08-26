"""Historical batch ingestion: large batches, dedup, and resumability.

Business-correctness tests, not OCR tests -- every fixture is a plain
`.txt` file so the deterministic text importer is exercised directly.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import DocumentSourceType, ExtractionStatus, ImportReviewStatus, PurchaseOrderMatchStatus
from app.models import ImportedDocument
from app.services.import_service import (
    compute_file_hash,
    ingest_purchase_order_batch,
    ingest_quotation_batch,
    list_imported_documents,
)


def _write_quotation(tmp_path: Path, name: str, *, reference: str, net: str = "1,000.00") -> Path:
    path = tmp_path / name
    path.write_text(f"Quotation Number: {reference}\nQuotation Date: 01/01/2025\nNet Amount: {net}\n", encoding="utf-8")
    return path


def _write_po(tmp_path: Path, name: str, *, reference: str) -> Path:
    path = tmp_path / name
    path.write_text(f"Quotation Reference: {reference}\n", encoding="utf-8")
    return path


# --- Large batches ---------------------------------------------------------------


def test_large_batch_stages_every_new_quotation_file(db_session: Session, tmp_path: Path) -> None:
    paths = [_write_quotation(tmp_path, f"quote_{i}.txt", reference=f"Q-{i:04d}") for i in range(40)]

    summary = ingest_quotation_batch(db_session, paths)

    assert summary.staged_count == 40
    assert summary.failed_count == 0
    assert summary.skipped_duplicate_count == 0
    assert summary.resumed_count == 0
    assert len(list_imported_documents(db_session)) == 40


def test_large_po_batch_stages_every_file_including_unmatched(db_session: Session, tmp_path: Path) -> None:
    paths = [_write_po(tmp_path, f"po_{i}.txt", reference=f"VN/QU/{i:04d}/25") for i in range(30)]

    summary = ingest_purchase_order_batch(db_session, paths)

    assert summary.staged_count == 30
    documents = list_imported_documents(db_session)
    assert len(documents) == 30
    assert all(d.purchase_order_candidate.match_status == PurchaseOrderMatchStatus.UNMATCHED for d in documents)


# --- Duplicate files ---------------------------------------------------------------


def test_batch_skips_a_file_already_terminally_processed(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation(tmp_path, "q.txt", reference="Q-DUP")

    first = ingest_quotation_batch(db_session, [path])
    assert first.staged_count == 1

    # Re-running the batch over the same (or a growing) file list must not
    # re-stage or re-extract an already-completed document.
    second = ingest_quotation_batch(db_session, [path])
    assert second.staged_count == 0
    assert second.skipped_duplicate_count == 1
    assert len(list_imported_documents(db_session)) == 1


def test_batch_does_not_auto_retry_a_failed_document(db_session: Session, tmp_path: Path) -> None:
    """A FAILED extraction already ran to completion once and may be a
    permanent, deterministic problem -- it must never be silently
    re-attempted on every batch re-run (that would violate "avoid
    re-processing identical documents" for the files least likely to ever
    succeed)."""
    path = tmp_path / "corrupt.txt"
    path.write_text("irrelevant", encoding="utf-8")
    document = ImportedDocument(
        source_type=DocumentSourceType.LOCAL,
        original_path=str(path),
        filename=path.name,
        extension="txt",
        file_size=path.stat().st_size,
        file_hash=compute_file_hash(path),
        extraction_status=ExtractionStatus.FAILED,
        extraction_error="Simulated permanent failure",
        review_status=ImportReviewStatus.NEEDS_REVIEW,
    )
    db_session.add(document)
    db_session.flush()

    summary = ingest_quotation_batch(db_session, [path])

    assert summary.skipped_duplicate_count == 1
    assert summary.resumed_count == 0
    db_session.refresh(document)
    assert document.extraction_status == ExtractionStatus.FAILED  # untouched


# --- Interrupted / resumed processing -----------------------------------------


def test_batch_resumes_a_quotation_document_interrupted_mid_extraction(
    db_session: Session, tmp_path: Path
) -> None:
    """Simulates a process killed between hashing/staging and extraction
    finishing: a staging row exists, but extraction_status never reached a
    terminal state. Re-running the batch must complete it in place, never
    create a second row for the same file."""
    path = _write_quotation(tmp_path, "q.txt", reference="Q-RESUME", net="7,000.00")
    document = ImportedDocument(
        source_type=DocumentSourceType.LOCAL,
        original_path=str(path),
        filename=path.name,
        extension="txt",
        file_size=path.stat().st_size,
        file_hash=compute_file_hash(path),
        extraction_status=ExtractionStatus.PENDING,
        review_status=ImportReviewStatus.NEEDS_REVIEW,
    )
    db_session.add(document)
    db_session.flush()

    summary = ingest_quotation_batch(db_session, [path])

    assert summary.resumed_count == 1
    assert summary.staged_count == 0
    db_session.refresh(document)
    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert document.quotation_candidate is not None
    assert document.quotation_candidate.quotation_number == "Q-RESUME"
    assert len(list_imported_documents(db_session)) == 1


def test_batch_resumes_a_po_document_interrupted_mid_extraction(db_session: Session, tmp_path: Path) -> None:
    path = _write_po(tmp_path, "po.txt", reference="VN/QU/500/25")
    document = ImportedDocument(
        source_type=DocumentSourceType.LOCAL,
        original_path=str(path),
        filename=path.name,
        extension="txt",
        file_size=path.stat().st_size,
        file_hash=compute_file_hash(path),
        extraction_status=ExtractionStatus.EXTRACTING,
        review_status=ImportReviewStatus.NEEDS_REVIEW,
    )
    db_session.add(document)
    db_session.flush()

    summary = ingest_purchase_order_batch(db_session, [path])

    assert summary.resumed_count == 1
    db_session.refresh(document)
    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert document.purchase_order_candidate is not None
    assert document.purchase_order_candidate.po_reference_number == "VN/QU/500/25"
    assert len(list_imported_documents(db_session)) == 1


# --- One bad file never aborts the batch ----------------------------------------


def test_batch_does_not_abort_when_one_file_is_missing(db_session: Session, tmp_path: Path) -> None:
    good = _write_quotation(tmp_path, "good.txt", reference="Q-GOOD")
    missing = tmp_path / "does_not_exist.txt"

    summary = ingest_quotation_batch(db_session, [missing, good])

    assert summary.failed_count == 1
    assert summary.staged_count == 1
    assert summary.outcomes[0].action == "failed"
    assert summary.outcomes[0].document_id is None
    assert summary.outcomes[1].action == "staged"
    assert len(list_imported_documents(db_session)) == 1


# --- Source immutability --------------------------------------------------------


def test_source_files_remain_byte_identical_after_batch_ingestion(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation(tmp_path, "q.txt", reference="Q-IMMUTABLE")
    original_bytes = path.read_bytes()
    original_hash = compute_file_hash(path)

    ingest_quotation_batch(db_session, [path])

    assert path.read_bytes() == original_bytes
    assert compute_file_hash(path) == original_hash
