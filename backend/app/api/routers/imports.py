"""Historical quotation import -- a REST surface over the existing,
already-built desktop-era import/OCR pipeline
(`app/services/import_service.py`, `app/core/import_segmentation.py`,
`app/core/ocr_extraction.py`, etc. -- see backend/IMPORT_ARCHITECTURE.md)
plus the durable ingestion queue and batch lifecycle added on top of it
for production reliability (`app/services/import_queue_service.py`,
`app/models/import_staging.ImportJob` -- see this feature's own report).

Gated behind `quotations.create` throughout: importing a historical
quotation is, once confirmed, exactly the same business action as
creating one by hand, and that permission already exists and is already
granted to the right roles (see supabase/migrations) -- no new
`app_permission` enum value was added for this, deliberately, since
that would need its own live Supabase migration this session cannot
safely apply blind (see this feature's own report).

Deliberately narrow scope for this first pass, matching the "controlled
pilot-friendly workflow" requirement: single-document-per-candidate
review/confirm only (no sequential-segmentation review UI -- see
`import_service.list_segments`/`accept_segment`/etc., not wired up
here yet) and quotation documents only (not the separate
client-award-evidence/purchase-order pipeline). Every endpoint here
wraps an existing, already-tested service function; none of the actual
staging/extraction/matching/confirmation logic is reimplemented.

Upload no longer runs extraction itself, not even in the background of
this process (see `upload_batch_documents`'s own docstring): it persists
each file and creates a QUEUED `ImportJob`, then returns. A separate
worker process (`app/worker.py`) is what actually calls
`import_service.run_extraction` -- this router never does.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_imports import (
    BatchUploadAccepted,
    ConfirmImportRequest,
    ImportBatchCreate,
    ImportBatchRead,
    ImportBatchUpdate,
    ImportDashboardSummaryRead,
    ImportedDocumentRead,
    ImportedDocumentSummary,
    ImportedQuotationCandidateRead,
    RejectImportRequest,
    UpdateQuotationCandidateRequest,
)
from app.core import document_storage
from app.core.config import settings
from app.core.document_preview import get_page_count, render_page_preview
from app.models.import_staging import ImportBatch, ImportedDocument, ImportJob
from app.services import import_queue_service, import_service
from app.services.import_dashboard_service import compute_import_dashboard_summary
from app.services.errors import ValidationError

router = APIRouter(prefix="/imports", tags=["imports"])

_PERMISSION = "quotations.create"
_logger = logging.getLogger("app.api")


def _get_batch_or_404(session: Session, batch_id: int) -> ImportBatch:
    batch = import_service.get_import_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    return batch


def _batch_read(session: Session, batch: ImportBatch) -> ImportBatchRead:
    return ImportBatchRead(
        id=batch.id,
        label=batch.label,
        notes=batch.notes,
        staged_count=batch.staged_count,
        resumed_count=batch.resumed_count,
        skipped_duplicate_count=batch.skipped_duplicate_count,
        failed_count=batch.failed_count,
        completed_at=batch.completed_at,
        archived_at=batch.archived_at,
        created_at=batch.created_at,
        status=import_queue_service.compute_batch_lifecycle_status(session, batch).value,
    )


def _get_document_or_404(session: Session, document_id: int) -> ImportedDocument:
    document = import_service.get_imported_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imported document not found.")
    return document


def _candidate_read(document: ImportedDocument) -> ImportedQuotationCandidateRead | None:
    candidate = document.quotation_candidate
    if candidate is None:
        return None
    try:
        confidence = json.loads(candidate.field_confidence) if candidate.field_confidence else {}
    except (TypeError, ValueError):
        # A malformed confidence blob must never hide the extracted
        # field values themselves from a reviewer -- fall back to no
        # confidence info rather than 500ing the whole document view.
        confidence = {}
    return ImportedQuotationCandidateRead(
        quotation_number=candidate.quotation_number,
        quotation_date=candidate.quotation_date,
        client_name=candidate.client_name,
        project_name=candidate.project_name,
        project_number=candidate.project_number,
        description=candidate.description,
        currency=candidate.currency,
        net_value=candidate.net_value,
        tax_value=candidate.tax_value,
        gross_value=candidate.gross_value,
        valid_until=candidate.valid_until,
        payment_terms=candidate.payment_terms,
        notes=candidate.notes,
        field_confidence=confidence if isinstance(confidence, dict) else {},
    )


@router.post("/batches", response_model=ImportBatchRead, status_code=status.HTTP_201_CREATED)
def create_batch(
    payload: ImportBatchCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportBatchRead:
    batch = import_service.create_import_batch(session, label=payload.label)
    return _batch_read(session, batch)


@router.get("/batches", response_model=list[ImportBatchRead])
def list_batches(
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> list[ImportBatchRead]:
    return [_batch_read(session, b) for b in import_service.list_import_batches(session)]


@router.get("/batches/{batch_id}", response_model=ImportBatchRead)
def get_batch(
    batch_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportBatchRead:
    return _batch_read(session, _get_batch_or_404(session, batch_id))


@router.patch("/batches/{batch_id}", response_model=ImportBatchRead)
def update_batch(
    batch_id: int,
    payload: ImportBatchUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportBatchRead:
    """P10's deliberately minimal "Edit batch" -- rename the label and/or
    set notes. Refuses on an archived (read-only) batch."""
    batch = _get_batch_or_404(session, batch_id)
    try:
        import_queue_service.rename_import_batch(session, batch, label=payload.label, notes=payload.notes)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _batch_read(session, batch)


@router.delete("/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_batch(
    batch_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> None:
    """P9's batch lifecycle: hard-deletes an EMPTY batch, or a STAGING
    batch with nothing confirmed in it yet -- refuses (422, with a clear
    reason) for anything PROCESSING/COMPLETED/ARCHIVED, or STAGING with
    at least one confirmed document. See `import_queue_service.
    delete_import_batch`'s own docstring for the exact rules; this route
    only marshals the call."""
    batch = _get_batch_or_404(session, batch_id)
    try:
        import_queue_service.delete_import_batch(session, batch)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/archive", response_model=ImportBatchRead)
def archive_batch(
    batch_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportBatchRead:
    batch = _get_batch_or_404(session, batch_id)
    try:
        import_queue_service.archive_import_batch(session, batch)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _batch_read(session, batch)


@router.post("/batches/{batch_id}/cancel", response_model=ImportBatchRead)
def cancel_batch(
    batch_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportBatchRead:
    """Stops future processing of this batch's still-QUEUED documents
    (P9's "Cancel" action on a PROCESSING batch) -- a job already
    PROCESSING right now is left alone; see `import_queue_service.
    cancel_batch_jobs`'s own docstring on why."""
    batch = _get_batch_or_404(session, batch_id)
    import_queue_service.cancel_batch_jobs(session, batch)
    return _batch_read(session, batch)


@router.get("/batches/{batch_id}/summary", response_model=ImportDashboardSummaryRead)
def get_batch_summary(
    batch_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportDashboardSummaryRead:
    """The lightweight status endpoint the queue UI polls (P16) -- plain
    `COUNT` queries only, never the documents' own OCR/candidate
    payloads. `queued`/`processing` come from the `import_jobs` table
    (the queue's own live state); everything else is `ImportedDocument`-
    derived exactly as before this feature."""
    _get_batch_or_404(session, batch_id)
    summary = compute_import_dashboard_summary(session, batch_id=batch_id)
    queue = import_queue_service.compute_queue_summary(session, batch_id=batch_id)
    return ImportDashboardSummaryRead(
        total=summary.total,
        queued=queue.queued,
        processing=queue.processing,
        extraction_complete=summary.extraction_complete,
        needs_review=summary.needs_review,
        confirmed=summary.confirmed,
        rejected=summary.rejected,
        failed=summary.failed,
        duplicates=summary.duplicates,
        purchase_order_count=summary.purchase_order_count,
    )


@router.get("/batches/{batch_id}/documents", response_model=list[ImportedDocumentSummary])
def list_batch_documents(
    batch_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> list[ImportedDocumentSummary]:
    """Includes each document's own `ImportJob` state (P7/P8's "Attempts"/
    "Last error"/retry-eligibility columns) -- one extra indexed query
    (`ImportJob.batch_id`, already indexed -- see that model) rather than
    N+1 per-document lookups."""
    _get_batch_or_404(session, batch_id)
    documents = import_service.list_imported_documents(session, batch_id=batch_id)
    jobs_by_document = {
        job.imported_document_id: job
        for job in session.execute(select(ImportJob).where(ImportJob.batch_id == batch_id)).scalars().all()
    }
    rows = []
    for document in documents:
        job = jobs_by_document.get(document.id)
        row = ImportedDocumentSummary.model_validate(document)
        row.job_status = job.status.value if job is not None else None
        row.job_attempts = job.attempts if job is not None else None
        row.job_last_error = job.last_error if job is not None else None
        rows.append(row)
    return rows


@router.post(
    "/batches/{batch_id}/documents",
    response_model=BatchUploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_batch_documents(
    batch_id: int,
    files: list[UploadFile],
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> BatchUploadAccepted:
    """Writes each uploaded file to `settings.imports_storage_dir`
    (fast, synchronous disk I/O -- exactly today's per-request cost,
    nothing OCR-shaped), best-effort mirrors it to durable Supabase
    Storage (`app.core.document_storage`; a failure here is logged and
    the upload still succeeds -- the local copy already written is
    enough for this request, and `ensure_present` transparently repairs
    a missing local copy later from durable storage if this upload DID
    succeed there), creates the `ImportedDocument` row, and creates a
    QUEUED `ImportJob` for it. Extraction itself never runs on this
    request thread, in any form -- not inline, not as a `BackgroundTask`
    (see this router's own module docstring on why that mechanism was
    removed): a separate worker process (`app/worker.py`) claims the job
    and calls `import_service.run_extraction` completely independently
    of this HTTP request's lifetime. 202 Accepted reflects that
    honestly -- nothing has been extracted yet when this response is
    sent, only accepted and queued.

    A file whose exact bytes already exist as another staged document is
    never re-staged: if that existing document is still mid-pipeline
    (PENDING/EXTRACTING/OCR_REQUIRED), this instead ensures it has a
    queued job (a genuine "resume"); otherwise it's counted as a
    duplicate and nothing new happens for it -- the same rule
    `_ingest_batch` already applies for the desktop app's batch
    ingestion, reused here via `import_service.is_resumable_extraction_status`.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No files were uploaded.")

    batch = _get_batch_or_404(session, batch_id)
    if batch.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This batch is archived and read-only -- create a new batch to upload more documents.",
        )
    storage_dir = settings.imports_storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)

    accepted_files: list[str] = []
    document_ids: list[int] = []
    accepted_count = 0
    duplicate_count = 0
    queued_count = 0
    resumed_count = 0

    for upload in files:
        original_name = upload.filename or "upload"
        suffix = Path(original_name).suffix
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        dest = storage_dir / stored_name
        data = upload.file.read()
        with dest.open("wb") as f:
            f.write(data)

        file_hash = import_service.compute_file_hash(dest)
        existing = import_service.find_existing_by_hash(session, file_hash)
        if existing is not None:
            dest.unlink(missing_ok=True)  # bytes already durably staged under `existing` -- no second copy needed
            accepted_files.append(original_name)
            if import_service.is_resumable_extraction_status(existing.extraction_status):
                import_queue_service.enqueue_import_job(session, existing)
                document_ids.append(existing.id)
                queued_count += 1
                resumed_count += 1
            else:
                duplicate_count += 1
            continue

        try:
            document = import_service.stage_document_for_queue(
                session, dest, original_filename=original_name, batch_id=batch.id
            )
        except ValidationError:
            # A concurrent request staged the identical hash between our
            # check above and here -- vanishingly rare, but handled the
            # same way as an ordinary duplicate rather than failing the
            # whole upload.
            dest.unlink(missing_ok=True)
            duplicate_count += 1
            accepted_files.append(original_name)
            continue

        try:
            key = document_storage.object_key_for(
                "QUOTATION",
                year=document.created_at.year if document.created_at else date.today().year,
                batch_id=batch.id,
                document_id=document.id,
                suffix=document.extension,
            )
            result = document_storage.upload_bytes(
                data, key=key, content_type=upload.content_type or "application/octet-stream"
            )
            if result is not None:
                document.storage_bucket, document.storage_key = result
                session.flush()
        except document_storage.DocumentStorageError:
            _logger.exception("Could not upload imported document %s to durable storage", document.id)

        import_queue_service.enqueue_import_job(session, document)
        accepted_files.append(original_name)
        document_ids.append(document.id)
        accepted_count += 1
        queued_count += 1

    # Batch-level bookkeeping (`ImportBatchRead.staged_count`/etc.) --
    # mirrors `_ingest_batch`'s own accounting exactly (see that
    # function), kept up to date here too since this route no longer
    # goes through it at all. `completed_at` means "this upload call
    # finished", same as before -- a batch can receive more than one
    # upload call over its life, each one overwriting it.
    batch.staged_count += accepted_count
    batch.resumed_count += resumed_count
    batch.skipped_duplicate_count += duplicate_count
    batch.completed_at = datetime.now(UTC).replace(tzinfo=None)
    session.flush()

    return BatchUploadAccepted(
        batch_id=batch.id,
        accepted_files=accepted_files,
        accepted_count=accepted_count,
        duplicate_count=duplicate_count,
        queued_count=queued_count,
        document_ids=document_ids,
    )


@router.post("/documents/{document_id}/retry", response_model=ImportedDocumentRead)
def retry_document(
    document_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportedDocumentRead:
    """P8's "Retry" action -- re-queues the same document (never a
    duplicate) for another extraction attempt with a fresh attempt
    budget. Allowed from any state; a document that's already fine
    (CONFIRMED, currently processing) simply gets re-queued harmlessly --
    the frontend only shows this action for FAILED/UNSUPPORTED/
    OCR_REQUIRED documents in practice, but the route itself doesn't
    need to duplicate that judgment."""
    document = _get_document_or_404(session, document_id)
    import_queue_service.retry_import_job(session, document)
    return get_document(document_id, session=session, _user=_user)


def _ensure_local_copy(document: ImportedDocument) -> Path:
    """Restores `document`'s bytes to local disk from durable storage if
    a redeploy (or a fresh process) means they're not there right now --
    see `document_storage.ensure_present`'s own docstring. A no-op,
    returning the path unchanged, when the file is already local or no
    durable copy was ever recorded; every existing caller's "file not
    found" handling is completely unaffected either way."""
    return document_storage.ensure_present(
        original_path=document.original_path,
        storage_bucket=document.storage_bucket,
        storage_key=document.storage_key,
    )


def _page_count_for(document: ImportedDocument) -> int | None:
    """`None` whenever a page-by-page preview isn't available -- a
    non-PDF document, or a PDF `get_page_count` can't open (moved/
    deleted file, corrupted, password-protected). Deliberately swallows
    every such failure rather than letting a preview nicety turn a
    document-read request into a 500 -- the reviewer can always still
    see and edit the extracted fields even with no preview panel."""
    if document.extension.lower() != "pdf":
        return None
    try:
        return get_page_count(_ensure_local_copy(document))
    except (FileNotFoundError, ValueError):
        return None


@router.get("/documents/{document_id}", response_model=ImportedDocumentRead)
def get_document(
    document_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportedDocumentRead:
    document = _get_document_or_404(session, document_id)
    job = session.execute(
        select(ImportJob).where(ImportJob.imported_document_id == document.id)
    ).scalar_one_or_none()
    return ImportedDocumentRead(
        id=document.id,
        batch_id=document.batch_id,
        filename=document.filename,
        file_size=document.file_size,
        document_kind=document.document_kind,
        extraction_status=document.extraction_status,
        review_status=document.review_status,
        extraction_error=document.extraction_error,
        created_at=document.created_at,
        job_status=job.status.value if job is not None else None,
        job_attempts=job.attempts if job is not None else None,
        job_last_error=job.last_error if job is not None else None,
        resulting_client_id=document.resulting_client_id,
        resulting_project_id=document.resulting_project_id,
        resulting_quotation_id=document.resulting_quotation_id,
        quotation_candidate=_candidate_read(document),
        page_count=_page_count_for(document),
    )


@router.get("/documents/{document_id}/pages/{page_number}")
def get_document_page_preview(
    document_id: int,
    page_number: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> Response:
    """Renders one page of the ORIGINAL source document to a PNG, for
    the review workspace's side-by-side viewer -- reuses
    `app.core.document_preview.render_page_preview` exactly as-is (the
    same rasterization the desktop app's segment-boundary review dialog
    would use), never a new rendering path. Read-only: never touches
    `document.original_path` itself, only opens it for rendering.

    PDF only for now, matching what `render_page_preview` actually
    supports -- an Excel/Word/CSV/text document has no page-image
    concept to render, and `ImportedDocumentRead.page_count` is already
    `None` for those so the frontend never tries to call this for them.
    """
    document = _get_document_or_404(session, document_id)
    if document.extension.lower() != "pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Page preview is only available for PDF documents.",
        )
    try:
        png_bytes = render_page_preview(_ensure_local_copy(document), page_number)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return Response(content=png_bytes, media_type="image/png")


@router.patch("/documents/{document_id}/candidate", response_model=ImportedDocumentRead)
def update_document_candidate(
    document_id: int,
    payload: UpdateQuotationCandidateRequest,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportedDocumentRead:
    """Reviewer corrections to one or more extracted quotation fields --
    wraps the existing, already-tested `import_service.update_quotation_
    candidate` (the same function the desktop app's review dialog already
    calls; see that function's own docstring on why a genuine edit also
    clears the field's LOW/NEEDS_REVIEW confidence flag). `exclude_unset`
    means only fields the caller actually included in the request body
    are applied -- omitted fields are left untouched, but a field sent
    as `null` is deliberately cleared.
    """
    document = _get_document_or_404(session, document_id)
    candidate = document.quotation_candidate
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This document has no extracted quotation data to edit yet.",
        )
    fields = payload.model_dump(exclude_unset=True)
    try:
        import_service.update_quotation_candidate(session, document, candidate, **fields)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return get_document(document_id, session=session, _user=_user)


@router.post("/documents/{document_id}/confirm", response_model=ImportedDocumentRead)
def confirm_document(
    document_id: int,
    payload: ConfirmImportRequest,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportedDocumentRead:
    document = _get_document_or_404(session, document_id)
    try:
        import_service.confirm_import(
            session,
            document,
            client_id=payload.client_id,
            new_client_name=payload.new_client_name,
            project_id=payload.project_id,
            new_project_name=payload.new_project_name,
            new_project_code=payload.new_project_code,
            quotation_id=payload.quotation_id,
            include_boq=payload.include_boq,
            acknowledge_revision_conflict=payload.acknowledge_revision_conflict,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return get_document(document_id, session=session, _user=_user)


@router.post("/documents/{document_id}/reject", response_model=ImportedDocumentRead)
def reject_document(
    document_id: int,
    payload: RejectImportRequest,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportedDocumentRead:
    document = _get_document_or_404(session, document_id)
    try:
        import_service.reject_import(session, document, reason=payload.reason)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return get_document(document_id, session=session, _user=_user)
