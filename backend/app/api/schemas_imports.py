"""Pydantic request/response models for the historical quotation import
API (`app/api/routers/imports.py`).

Every response model mirrors an existing `app/services/import_service.py`
/ `app/models/import_staging.py` shape as closely as possible -- this
router is a thin REST wrapper around that already-built, already-tested
pipeline, not a new one.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str | None
    notes: str | None = None
    staged_count: int
    resumed_count: int
    skipped_duplicate_count: int
    failed_count: int
    completed_at: datetime | None
    archived_at: datetime | None = None
    created_at: datetime
    #: Derived (P9) -- see `app.core.enums.BatchLifecycleStatus` /
    #: `import_queue_service.compute_batch_lifecycle_status`. Never a
    #: stored column; computed fresh on every read.
    status: str


class ImportBatchCreate(BaseModel):
    label: str | None = Field(default=None, max_length=255)


class ImportBatchUpdate(BaseModel):
    """`PATCH /imports/batches/{id}` -- P10's deliberately minimal "Edit
    batch": label and/or notes. Omit a field to leave it untouched;
    every field is otherwise applied as given (including clearing it
    with an empty string)."""

    label: str | None = None
    notes: str | None = None


class ImportDashboardSummaryRead(BaseModel):
    total: int
    #: Job-table-derived (P16) -- how many of this batch's documents have
    #: a queued/processing `ImportJob` right now. Distinct from
    #: `needs_review`/`confirmed`/etc. below, which are all
    #: `ImportedDocument`-derived exactly as before.
    queued: int
    processing: int
    extraction_complete: int
    needs_review: int
    confirmed: int
    rejected: int
    failed: int
    duplicates: int | None
    purchase_order_count: int


class BatchUploadAccepted(BaseModel):
    """Response for `POST /imports/batches/{batch_id}/documents` (P15).
    Returned as soon as every file's bytes are durably persisted and
    queued -- before any OCR/extraction has run, which is what makes
    this endpoint fast regardless of how many files were uploaded or how
    slow OCR on any one of them will be. `accepted_files` names every
    file the browser sent, including duplicates (rejected before
    queuing, per `document_ids`/`queued_count` not counting them) --
    the caller should poll `GET /imports/batches/{batch_id}/status` (or
    `.../documents`) to watch queued documents progress."""

    batch_id: int
    accepted_files: list[str]
    accepted_count: int
    duplicate_count: int
    queued_count: int
    document_ids: list[int]


class ImportedQuotationCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quotation_number: str | None
    quotation_date: date | None
    client_name: str | None
    project_name: str | None
    project_number: str | None
    description: str | None
    currency: str | None
    net_value: Decimal | None
    tax_value: Decimal | None
    gross_value: Decimal | None
    valid_until: date | None
    payment_terms: str | None
    notes: str | None
    #: Small JSON dict (field name -> ConfidenceLevel string), decoded
    #: from `ImportedQuotationCandidate.field_confidence` by the route
    #: (stored as a raw JSON-text column, not a JSON column type -- see
    #: that model).
    field_confidence: dict[str, str] = Field(default_factory=dict)


class ImportedDocumentSummary(BaseModel):
    """One row in the batch document list -- deliberately narrower than
    `ImportedDocumentRead` (no candidate fields), matching what a status
    table needs versus what the single-document review view needs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int | None
    filename: str
    file_size: int
    document_kind: str
    extraction_status: str
    review_status: str
    extraction_error: str | None
    created_at: datetime
    #: The queue's own view of this document (P7/P8) -- `None` only for
    #: a document staged before `ImportJob` existed and never retried
    #: since (every document staged through the web upload route always
    #: has exactly one). Populated by the router joining `ImportJob`
    #: alongside the document, not a model relationship read here.
    job_status: str | None = None
    job_attempts: int | None = None
    job_last_error: str | None = None


class ImportedDocumentRead(ImportedDocumentSummary):
    """`GET /imports/documents/{id}` -- the single-document review view.
    `quotation_candidate` is `None` for a document extraction hasn't
    finished for yet, or one segmented into more than one candidate
    (out of this feature's current scope -- see this feature's own
    report; segmentation review has its own richer UI not exposed here
    yet).

    `page_count` is `None` whenever a page-by-page preview isn't
    available -- a non-PDF document (Excel/Word/CSV/text/image), or a
    PDF the router couldn't open (see `get_document`'s own try/except:
    this is a display nicety, not something that should ever turn a
    document-read request into a 500). Never fabricated -- the frontend
    must treat `None` as "no preview", not as "one page"."""

    resulting_client_id: int | None
    resulting_project_id: int | None
    resulting_quotation_id: int | None
    quotation_candidate: ImportedQuotationCandidateRead | None
    page_count: int | None = None


class UpdateQuotationCandidateRequest(BaseModel):
    """`PATCH /imports/documents/{id}/candidate` -- reviewer corrections
    to one or more extracted quotation fields, applied before confirming.
    Mirrors `import_service._QUOTATION_EDITABLE_FIELDS` exactly (the
    route rejects anything else via `update_quotation_candidate` itself).

    Every field is optional and the route reads only the ones the
    caller actually set (`payload.model_dump(exclude_unset=True)`) --
    omitting a field leaves it untouched, but sending it as `null`
    deliberately clears it (e.g. the reviewer decides an extracted
    currency was wrong and there's nothing to replace it with yet)."""

    quotation_number: str | None = None
    quotation_date: date | None = None
    client_name: str | None = None
    project_name: str | None = None
    project_number: str | None = None
    description: str | None = None
    currency: str | None = None
    net_value: Decimal | None = None
    tax_value: Decimal | None = None
    gross_value: Decimal | None = None
    valid_until: date | None = None
    payment_terms: str | None = None
    notes: str | None = None


class ConfirmImportRequest(BaseModel):
    """Mirrors `import_service.confirm_import`'s own parameters exactly
    -- this route only marshals them, never re-derives or second-guesses
    them. Exactly one of `client_id`/`new_client_name` and one of
    `project_id`/`new_project_name` should be given (both `None` is a
    validation error `confirm_import` itself already raises)."""

    client_id: int | None = None
    new_client_name: str | None = None
    project_id: int | None = None
    new_project_name: str | None = None
    new_project_code: str | None = None
    quotation_id: int | None = None
    include_boq: bool = True
    acknowledge_revision_conflict: bool = False


class RejectImportRequest(BaseModel):
    reason: str | None = None
