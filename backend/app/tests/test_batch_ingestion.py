"""Historical batch ingestion: large batches, dedup, and resumability.

Business-correctness tests, not OCR tests -- every fixture is a plain
`.txt` file so the deterministic text importer is exercised directly.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import DocumentSourceType, ExtractionStatus, ImportReviewStatus, ClientAwardEvidenceMatchStatus
from app.models import ImportBatch, ImportedDocument
from app.services.import_service import (
    compute_file_hash,
    create_import_batch,
    ingest_client_award_evidence_batch,
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

    summary = ingest_client_award_evidence_batch(db_session, paths)

    assert summary.staged_count == 30
    documents = list_imported_documents(db_session)
    assert len(documents) == 30
    assert all(d.client_award_evidence_candidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED for d in documents)


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

    summary = ingest_client_award_evidence_batch(db_session, [path])

    assert summary.resumed_count == 1
    db_session.refresh(document)
    assert document.extraction_status == ExtractionStatus.EXTRACTION_COMPLETE
    assert document.client_award_evidence_candidate is not None
    assert document.client_award_evidence_candidate.po_reference_number == "VN/QU/500/25"
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


# --- Durable ImportBatch tracking (scale groundwork) ----------------------------


def test_ingesting_with_a_batch_tags_every_newly_staged_document(db_session: Session, tmp_path: Path) -> None:
    batch = create_import_batch(db_session, label="2018 archive box 3")
    paths = [_write_quotation(tmp_path, f"q_{i}.txt", reference=f"Q-B-{i}") for i in range(5)]

    ingest_quotation_batch(db_session, paths, batch=batch)

    documents = list_imported_documents(db_session)
    assert len(documents) == 5
    assert all(d.batch_id == batch.id for d in documents)


def test_ingesting_without_a_batch_leaves_batch_id_null(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation(tmp_path, "q.txt", reference="Q-NOBATCH")

    ingest_quotation_batch(db_session, [path])

    documents = list_imported_documents(db_session)
    assert documents[0].batch_id is None


def test_batch_records_its_own_outcome_counts(db_session: Session, tmp_path: Path) -> None:
    batch = create_import_batch(db_session)
    good = [_write_quotation(tmp_path, f"q_{i}.txt", reference=f"Q-C-{i}") for i in range(3)]
    missing = tmp_path / "does_not_exist.txt"

    ingest_quotation_batch(db_session, [*good, missing], batch=batch)

    # Re-run with an added duplicate of one already-staged file plus a new one.
    more = [good[0], _write_quotation(tmp_path, "q_new.txt", reference="Q-C-NEW")]
    ingest_quotation_batch(db_session, more, batch=batch)

    db_session.refresh(batch)
    assert batch.staged_count == 1  # only q_new.txt, the second call's own new file
    assert batch.skipped_duplicate_count == 1  # good[0], already terminally processed
    assert batch.failed_count == 0  # the missing file was only in the first call
    assert batch.completed_at is not None


def test_resuming_a_document_never_reassigns_its_original_batch(db_session: Session, tmp_path: Path) -> None:
    """A document staged under batch A, then swept up again by a later
    batch B's re-run (e.g. the same growing file list passed to both),
    must keep pointing at batch A -- re-running ingestion must never
    silently move a document's batch attribution."""
    batch_a = create_import_batch(db_session, label="A")
    path = _write_quotation(tmp_path, "q.txt", reference="Q-STAY")
    ingest_quotation_batch(db_session, [path], batch=batch_a)

    batch_b = create_import_batch(db_session, label="B")
    ingest_quotation_batch(db_session, [path], batch=batch_b)

    documents = list_imported_documents(db_session)
    assert len(documents) == 1
    assert documents[0].batch_id == batch_a.id


def test_create_import_batch_defaults_counts_to_zero_and_is_not_yet_completed(db_session: Session) -> None:
    batch = create_import_batch(db_session)
    assert batch.staged_count == 0
    assert batch.resumed_count == 0
    assert batch.skipped_duplicate_count == 0
    assert batch.failed_count == 0
    assert batch.completed_at is None
    assert isinstance(batch, ImportBatch)
