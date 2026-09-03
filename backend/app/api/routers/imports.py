"""Historical quotation import -- a REST surface over the existing,
already-built desktop-era import/OCR pipeline
(`app/services/import_service.py`, `app/core/import_segmentation.py`,
`app/core/ocr_extraction.py`, etc. -- see backend/IMPORT_ARCHITECTURE.md).

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
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_imports import (
    BatchUploadAccepted,
    ConfirmImportRequest,
    ImportBatchCreate,
    ImportBatchRead,
    ImportDashboardSummaryRead,
    ImportedDocumentRead,
    ImportedDocumentSummary,
    ImportedQuotationCandidateRead,
    RejectImportRequest,
    UpdateQuotationCandidateRequest,
)
from app.core.config import settings
from app.core.document_preview import get_page_count, render_page_preview
from app.database.session import session_scope
from app.models.import_staging import ImportedDocument
from app.services import import_service
from app.services.import_dashboard_service import compute_import_dashboard_summary
from app.services.errors import ValidationError

router = APIRouter(prefix="/imports", tags=["imports"])

_PERMISSION = "quotations.create"
_logger = logging.getLogger("app.api")


def _get_batch_or_404(session: Session, batch_id: int):
    batch = import_service.get_import_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    return batch


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
    return ImportBatchRead.model_validate(batch)


@router.get("/batches", response_model=list[ImportBatchRead])
def list_batches(
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> list[ImportBatchRead]:
    return [ImportBatchRead.model_validate(b) for b in import_service.list_import_batches(session)]


@router.get("/batches/{batch_id}", response_model=ImportBatchRead)
def get_batch(
    batch_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportBatchRead:
    return ImportBatchRead.model_validate(_get_batch_or_404(session, batch_id))


@router.get("/batches/{batch_id}/summary", response_model=ImportDashboardSummaryRead)
def get_batch_summary(
    batch_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportDashboardSummaryRead:
    _get_batch_or_404(session, batch_id)
    summary = compute_import_dashboard_summary(session, batch_id=batch_id)
    return ImportDashboardSummaryRead(
        total=summary.total,
        processing=summary.processing,
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
    _get_batch_or_404(session, batch_id)
    documents = import_service.list_imported_documents(session, batch_id=batch_id)
    return [ImportedDocumentSummary.model_validate(d) for d in documents]


def _process_uploaded_batch_files(
    batch_id: int, saved_paths: list[Path], original_names: dict[str, str]
) -> None:
    """Runs AFTER the HTTP response for `upload_batch_documents` has
    already been sent (see that route's `BackgroundTasks.add_task` call)
    -- this is what actually stages/hashes/extracts, off the request
    thread, so a slow OCR pass can never hang or time out the upload
    request itself. Opens its own database session: by the time this
    runs, the request's own `Depends(get_db)` session has already
    committed and closed, and a background job needs a session with its
    own independent lifetime regardless.

    Reuses `ingest_quotation_batch` completely unchanged -- every actual
    staging/hashing/dedup/extraction decision is still made by that same
    already-tested function; this only changes WHEN it's called relative
    to the HTTP response, never HOW it behaves.
    """
    with session_scope() as session:
        batch = import_service.get_import_batch(session, batch_id)
        if batch is None:
            # Nothing in this codebase ever deletes a batch -- this is
            # defensive, not an expected path.
            _logger.warning("Import batch %s vanished before background processing could run", batch_id)
            return
        try:
            summary = import_service.ingest_quotation_batch(session, saved_paths, batch=batch)
        except ValidationError:
            _logger.exception("Background import processing failed for batch %s", batch_id)
            return

        for outcome in summary.outcomes:
            # `stage_document` (inside ingest_quotation_batch) names the
            # document after the path it was actually given -- the
            # random uuid-prefixed storage filename, not what the
            # browser sent. Only true for a genuinely NEW document
            # ("staged"); a "resumed"/"skipped_duplicate" one already
            # has its original first-upload filename recorded.
            if outcome.action == "staged" and outcome.document_id is not None:
                original_name = original_names.get(str(outcome.path), outcome.path.name)
                staged_document = import_service.get_imported_document(session, outcome.document_id)
                if staged_document is not None:
                    staged_document.filename = original_name


@router.post(
    "/batches/{batch_id}/documents",
    response_model=BatchUploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_batch_documents(
    batch_id: int,
    files: list[UploadFile],
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> BatchUploadAccepted:
    """Writes each uploaded file to `settings.imports_storage_dir`
    (persistently -- see that setting's own docstring on why, and its
    known limitation on an ephemeral-disk host) under a random-uuid-
    prefixed name (never trusting the browser-supplied filename as a
    path component) -- fast, synchronous, just disk I/O. The actual
    staging/hashing/extraction (`_process_uploaded_batch_files` above)
    then runs as a FastAPI background task, AFTER this response is
    already sent: a scanned document's OCR pass has no fixed time
    budget, and running it inline risked hanging or timing out the
    upload request for exactly the documents this feature exists to
    handle. 202 Accepted (not 201 Created) reflects that honestly --
    nothing has been fully processed yet when this response is sent.
    `BackgroundTasks` is FastAPI's own built-in mechanism (no new
    dependency, no new infrastructure); the caller is expected to poll
    `GET .../documents` and `.../summary` to watch documents actually
    appear and progress (see the frontend's polling).
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No files were uploaded.")

    _get_batch_or_404(session, batch_id)
    storage_dir = settings.imports_storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    original_names: dict[str, str] = {}
    accepted_files: list[str] = []
    for upload in files:
        original_name = upload.filename or "upload"
        suffix = Path(original_name).suffix
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        dest = storage_dir / stored_name
        with dest.open("wb") as f:
            f.write(upload.file.read())
        saved_paths.append(dest)
        original_names[str(dest)] = original_name
        accepted_files.append(original_name)

    background_tasks.add_task(_process_uploaded_batch_files, batch_id, saved_paths, original_names)
    return BatchUploadAccepted(accepted_files=accepted_files)


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
        return get_page_count(Path(document.original_path))
    except (FileNotFoundError, ValueError):
        return None


@router.get("/documents/{document_id}", response_model=ImportedDocumentRead)
def get_document(
    document_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_PERMISSION)),
) -> ImportedDocumentRead:
    document = _get_document_or_404(session, document_id)
    return ImportedDocumentRead(
        id=document.id,
        batch_id=document.batch_id,
        filename=document.filename,
        document_kind=document.document_kind,
        extraction_status=document.extraction_status,
        review_status=document.review_status,
        extraction_error=document.extraction_error,
        created_at=document.created_at,
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
        png_bytes = render_page_preview(Path(document.original_path), page_number)
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
