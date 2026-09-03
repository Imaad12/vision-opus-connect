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
    staged_count: int
    resumed_count: int
    skipped_duplicate_count: int
    failed_count: int
    completed_at: datetime | None
    created_at: datetime


class ImportBatchCreate(BaseModel):
    label: str | None = Field(default=None, max_length=255)


class ImportDashboardSummaryRead(BaseModel):
    total: int
    processing: int
    needs_review: int
    confirmed: int
    rejected: int
    failed: int
    duplicates: int | None
    purchase_order_count: int


class BatchUploadAccepted(BaseModel):
    """Response for `POST /imports/batches/{batch_id}/documents`.

    Deliberately does NOT report per-file outcomes (staged/resumed/
    skipped_duplicate/failed) the way an earlier version of this
    endpoint did: actual staging/hashing/extraction now runs in a
    background task (see that route's docstring on why -- OCR can be
    slow enough to risk hanging the HTTP request), so those outcomes
    aren't known yet when this response is sent. The caller should poll
    `GET /imports/batches/{batch_id}/documents` (and the summary
    endpoint) to watch documents appear and move through
    PENDING -> EXTRACTING -> a terminal extraction_status."""

    accepted_files: list[str]


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
    document_kind: str
    extraction_status: str
    review_status: str
    extraction_error: str | None
    created_at: datetime


class ImportedDocumentRead(ImportedDocumentSummary):
    """`GET /imports/documents/{id}` -- the single-document review view.
    `quotation_candidate` is `None` for a document extraction hasn't
    finished for yet, or one segmented into more than one candidate
    (out of this feature's current scope -- see this feature's own
    report; segmentation review has its own richer UI not exposed here
    yet)."""

    resulting_client_id: int | None
    resulting_project_id: int | None
    resulting_quotation_id: int | None
    quotation_candidate: ImportedQuotationCandidateRead | None


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
