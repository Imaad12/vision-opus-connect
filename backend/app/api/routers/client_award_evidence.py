""""POs Awarded by Client" -- the sales/commercial-pipeline surface over
`app.models.client_award_evidence.ClientAwardEvidence` (see that model's
own module docstring, and `app.api.routers.purchase_orders`'s docstring,
for why this is deliberately NOT under `/purchase-orders`: that prefix is
the unrelated Supplier Purchase Order domain).

Every route here reuses `app.services.client_award_evidence_service`
unchanged from what the OCR-import pipeline already exercises -- the
only new service code is the manual-recording/document-attach functions
at the bottom of that module, added specifically because a reviewer
typing a PO in by hand has no `ImportedDocument`/staged candidate to
drive the existing `confirm_client_award_evidence_import`.

Permissions: `quotations.view` to read (recording or querying a client
award is, once confirmed, part of the same commercial record a
quotation already is), `quotations.approve` to record one or attach a
document to one -- the same permission `POST /quotation-versions/{id}/
award` already requires, since recording a PO is the same "this
quotation is now awarded" business event, just entered by hand instead
of extracted by OCR.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_sales import (
    ClientAwardEvidenceCreate,
    ClientAwardEvidenceDocumentRead,
    ClientAwardEvidenceRead,
)
from app.core import document_storage
from app.core.config import settings
from app.models import ClientAwardEvidence
from app.services import client_award_evidence_service, contract_service, quotation_service
from app.services.errors import ValidationError

router = APIRouter(tags=["client-award-evidence"])

_logger = logging.getLogger("app.api")

_VIEW_PERMISSION = "quotations.view"
_RECORD_PERMISSION = "quotations.approve"


def _get_quotation_or_404(session: Session, quotation_id: int):
    quotation = quotation_service.get_quotation(session, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")
    return quotation


def _get_client_award_evidence_or_404(session: Session, client_award_evidence_id: int) -> ClientAwardEvidence:
    evidence = client_award_evidence_service.get_client_award_evidence(session, client_award_evidence_id)
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client PO not found.")
    return evidence


def _read(session: Session, evidence: ClientAwardEvidence) -> ClientAwardEvidenceRead:
    """Assembles the response's denormalized/computed fields -- the
    quotation's own reference/quoted_value (for the "variance" display),
    whether this award traces back to an OCR-confirmed source document
    or was entered by hand, and whether a `Contract` already exists for
    its project. None of these are stored on `ClientAwardEvidence`
    itself; see that schema's own field-level docstrings."""
    quotation = evidence.quotation
    current_version = quotation_service.get_current_version(session, quotation)
    quoted_value = current_version.quoted_value if current_version else None
    variance = evidence.net_value - quoted_value if evidence.net_value is not None and quoted_value is not None else None

    document = client_award_evidence_service.get_client_award_evidence_source_document(session, evidence.id)
    # A document being present only means *some* file traces back to this
    # award -- it does not by itself mean OCR extracted it. A manually
    # recorded PO can have a PDF attached afterwards purely for provenance
    # (`attach_client_award_evidence_document`, which never creates a
    # staged OCR candidate); only a document that went through the
    # extraction/candidate pipeline (`client_award_evidence_candidate` set)
    # was actually read by OCR. Conflating the two would mislabel a
    # hand-typed award with a manually-attached file as "Imported (OCR)".
    source = "imported" if document is not None and document.client_award_evidence_candidate is not None else "manual"
    contract = contract_service.get_contract_for_project(session, quotation.project_id)

    return ClientAwardEvidenceRead(
        id=evidence.id,
        quotation_id=evidence.quotation_id,
        po_reference_number=evidence.po_reference_number,
        po_date=evidence.po_date,
        net_value=evidence.net_value,
        tax_value=evidence.tax_value,
        gross_value=evidence.gross_value,
        currency=evidence.currency,
        notes=evidence.notes,
        awarded_quotation_version_id=evidence.awarded_quotation_version_id,
        awarded_quotation_version=evidence.awarded_quotation_version,
        project=quotation.project,
        quotation_reference_number=quotation.reference_number,
        quoted_value=quoted_value,
        variance=variance,
        source=source,
        document=(
            ClientAwardEvidenceDocumentRead(id=document.id, filename=document.filename)
            if document is not None
            else None
        ),
        contracted=contract is not None,
        created_at=evidence.created_at,
        updated_at=evidence.updated_at,
    )


@router.get("/client-award-evidence", response_model=list[ClientAwardEvidenceRead])
def list_client_award_evidence(
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_VIEW_PERMISSION)),
) -> list[ClientAwardEvidenceRead]:
    return [_read(session, e) for e in client_award_evidence_service.list_client_award_evidence(session)]


@router.get("/client-award-evidence/{client_award_evidence_id}", response_model=ClientAwardEvidenceRead)
def get_client_award_evidence(
    client_award_evidence_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_VIEW_PERMISSION)),
) -> ClientAwardEvidenceRead:
    evidence = _get_client_award_evidence_or_404(session, client_award_evidence_id)
    return _read(session, evidence)


@router.get(
    "/quotations/{quotation_id}/client-award-evidence",
    response_model=list[ClientAwardEvidenceRead],
)
def list_client_award_evidence_for_quotation(
    quotation_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_VIEW_PERMISSION)),
) -> list[ClientAwardEvidenceRead]:
    _get_quotation_or_404(session, quotation_id)
    return [
        _read(session, e)
        for e in client_award_evidence_service.list_client_award_evidence_for_quotation(session, quotation_id)
    ]


@router.post(
    "/quotations/{quotation_id}/client-award-evidence",
    response_model=ClientAwardEvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def record_client_award_evidence(
    quotation_id: int,
    payload: ClientAwardEvidenceCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_RECORD_PERMISSION)),
) -> ClientAwardEvidenceRead:
    quotation = _get_quotation_or_404(session, quotation_id)
    try:
        evidence = client_award_evidence_service.record_client_award_evidence(
            session, quotation, **payload.model_dump()
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _read(session, evidence)


@router.post(
    "/client-award-evidence/{client_award_evidence_id}/document",
    response_model=ClientAwardEvidenceRead,
)
def attach_client_award_evidence_document(
    client_award_evidence_id: int,
    file: UploadFile,
    session: Session = Depends(get_db),
    _user=Depends(require_permission(_RECORD_PERMISSION)),
) -> ClientAwardEvidenceRead:
    """Attach a client PO PDF to an already-recorded award. Synchronous
    (unlike the historical-import batch upload, which backgrounds
    itself specifically because OCR has no fixed time budget) -- this
    is just a file write and a hash check, no extraction runs at all
    (see `client_award_evidence_service.attach_client_award_evidence_document`'s
    own docstring on why not), so there is nothing here that risks
    hanging the request.
    """
    evidence = _get_client_award_evidence_or_404(session, client_award_evidence_id)

    original_name = file.filename or "client-po"
    storage_dir = settings.imports_storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)
    dest = storage_dir / f"{uuid.uuid4().hex}{Path(original_name).suffix}"
    data = file.file.read()
    with dest.open("wb") as f:
        f.write(data)

    try:
        document = client_award_evidence_service.attach_client_award_evidence_document(
            session, evidence, dest, original_filename=original_name
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    # Durable storage (P5) -- same principle, same module, same
    # best-effort-on-failure behavior as the historical-import upload
    # route (app/api/routers/imports.py): the local write above already
    # succeeded, so a Supabase Storage hiccup here is logged, not fatal
    # to this request.
    try:
        key = document_storage.object_key_for(
            "PURCHASE_ORDER",
            year=document.created_at.year if document.created_at else date.today().year,
            batch_id=None,
            document_id=document.id,
            suffix=Path(original_name).suffix,
        )
        result = document_storage.upload_bytes(
            data, key=key, content_type=file.content_type or "application/octet-stream"
        )
        if result is not None:
            document.storage_bucket, document.storage_key = result
            session.flush()
    except document_storage.DocumentStorageError:
        _logger.exception("Could not upload client PO document %s to durable storage", document.id)

    return _read(session, evidence)
