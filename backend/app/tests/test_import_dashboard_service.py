"""Historical-import dashboard aggregation (H12) -- pure counting over
`ImportedDocument`/`ImportBatch`, built directly (no importer/OCR
involved) since this only tests the aggregation itself, not extraction.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.enums import (
    DocumentSourceType,
    ExtractionStatus,
    ImportDocumentKind,
    ImportReviewStatus,
)
from app.models import ImportedDocument
from app.services.import_dashboard_service import compute_import_dashboard_summary
from app.services.import_service import create_import_batch


def _document(
    *,
    filename: str,
    extraction_status: ExtractionStatus,
    review_status: ImportReviewStatus = ImportReviewStatus.NEEDS_REVIEW,
    document_kind: ImportDocumentKind = ImportDocumentKind.QUOTATION,
    batch_id: int | None = None,
) -> ImportedDocument:
    return ImportedDocument(
        source_type=DocumentSourceType.LOCAL,
        document_kind=document_kind,
        original_path=f"/tmp/{filename}",
        filename=filename,
        extension="txt",
        file_size=10,
        file_hash=f"hash-{filename}",
        extraction_status=extraction_status,
        review_status=review_status,
        batch_id=batch_id,
    )


def test_empty_summary(db_session: Session) -> None:
    summary = compute_import_dashboard_summary(db_session)
    assert summary.total == 0
    assert summary.processing == 0
    assert summary.needs_review == 0
    assert summary.confirmed == 0
    assert summary.rejected == 0
    assert summary.failed == 0
    assert summary.purchase_order_count == 0
    # Unscoped (no batch_id): duplicates cannot be derived from
    # ImportedDocument alone -- see ImportBatch's docstring.
    assert summary.duplicates is None


def test_counts_partition_documents_by_status(db_session: Session) -> None:
    db_session.add_all(
        [
            _document(filename="a.txt", extraction_status=ExtractionStatus.PENDING),
            _document(filename="b.txt", extraction_status=ExtractionStatus.EXTRACTING),
            _document(filename="c.txt", extraction_status=ExtractionStatus.OCR_REQUIRED),
            _document(
                filename="d.txt",
                extraction_status=ExtractionStatus.EXTRACTION_COMPLETE,
                review_status=ImportReviewStatus.NEEDS_REVIEW,
            ),
            _document(
                filename="e.txt",
                extraction_status=ExtractionStatus.EXTRACTION_COMPLETE,
                review_status=ImportReviewStatus.CONFIRMED,
            ),
            _document(
                filename="f.txt",
                extraction_status=ExtractionStatus.EXTRACTION_COMPLETE,
                review_status=ImportReviewStatus.REJECTED,
            ),
            _document(filename="g.txt", extraction_status=ExtractionStatus.FAILED),
            _document(filename="h.txt", extraction_status=ExtractionStatus.UNSUPPORTED),
            _document(filename="i.txt", extraction_status=ExtractionStatus.MULTIPLE_QUOTATIONS_DETECTED),
        ]
    )
    db_session.flush()

    summary = compute_import_dashboard_summary(db_session)

    assert summary.total == 9
    assert summary.processing == 3  # a, b, c
    assert summary.needs_review == 1  # d only
    assert summary.confirmed == 1  # e
    assert summary.rejected == 1  # f
    assert summary.failed == 3  # g, h, i


def test_ocr_required_counts_as_processing_not_failed(db_session: Session) -> None:
    db_session.add(_document(filename="a.txt", extraction_status=ExtractionStatus.OCR_REQUIRED))
    db_session.flush()

    summary = compute_import_dashboard_summary(db_session)

    assert summary.processing == 1
    assert summary.failed == 0


def test_purchase_order_count_only_counts_po_kind_documents(db_session: Session) -> None:
    db_session.add_all(
        [
            _document(
                filename="q.txt",
                extraction_status=ExtractionStatus.EXTRACTION_COMPLETE,
                document_kind=ImportDocumentKind.QUOTATION,
            ),
            _document(
                filename="po.txt",
                extraction_status=ExtractionStatus.EXTRACTION_COMPLETE,
                document_kind=ImportDocumentKind.PURCHASE_ORDER,
            ),
        ]
    )
    db_session.flush()

    summary = compute_import_dashboard_summary(db_session)

    assert summary.total == 2
    assert summary.purchase_order_count == 1


def test_scoping_to_a_batch_only_counts_that_batchs_documents(db_session: Session) -> None:
    batch_a = create_import_batch(db_session, label="A")
    batch_b = create_import_batch(db_session, label="B")
    db_session.add_all(
        [
            _document(filename="a1.txt", extraction_status=ExtractionStatus.PENDING, batch_id=batch_a.id),
            _document(filename="a2.txt", extraction_status=ExtractionStatus.PENDING, batch_id=batch_a.id),
            _document(filename="b1.txt", extraction_status=ExtractionStatus.PENDING, batch_id=batch_b.id),
        ]
    )
    db_session.flush()

    summary_a = compute_import_dashboard_summary(db_session, batch_id=batch_a.id)
    summary_b = compute_import_dashboard_summary(db_session, batch_id=batch_b.id)
    summary_all = compute_import_dashboard_summary(db_session)

    assert summary_a.total == 2
    assert summary_b.total == 1
    assert summary_all.total == 3


def test_duplicates_is_read_from_the_batchs_own_recorded_count(db_session: Session) -> None:
    batch = create_import_batch(db_session)
    batch.skipped_duplicate_count = 4
    db_session.flush()

    summary = compute_import_dashboard_summary(db_session, batch_id=batch.id)

    assert summary.duplicates == 4


def test_duplicates_is_none_for_an_unknown_batch_id(db_session: Session) -> None:
    summary = compute_import_dashboard_summary(db_session, batch_id=999999)
    assert summary.duplicates is None
    assert summary.total == 0
