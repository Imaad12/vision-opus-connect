"""Quotations -- backed entirely by the existing `quotation_service`.

This exposes the backend's real quotation/version model as-is: a
`Quotation` (reference number, one per tender opportunity) has one or
more immutable `QuotationVersion`s (the priced, dated, status-carrying
revisions -- see `quotation_service`'s module docstring for why award is
a one-way transition, never a re-edit).

That shape does not match the frontend's `quotations` table today (one
flat row per quotation, its own `quotation_items`/`quotation_approvals`
tables, and a different status vocabulary). Reconciling that is real,
separate frontend-integration work -- this router deliberately doesn't
flatten the backend's versioned model to fit the existing Supabase shape,
since that would mean inventing a shortcut around the very history/
immutability guarantees `quotation_service` exists to protect.

BOQ line items are read-only here: they are populated by the
document-import pipeline (`app.services.import_service`), which this
task does not touch. There is no "approval" endpoint because the
backend has no distinct approval step beyond submit/award -- see
`app.core.enums.QuotationStatus`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas import (
    BOQLineItemRead,
    QuotationAward,
    QuotationCreate,
    QuotationRead,
    QuotationRevisionCreate,
    QuotationVersionRead,
)
from app.services import project_service, quotation_service
from app.services.errors import ValidationError

router = APIRouter(tags=["quotations"])


def _get_quotation_or_404(session: Session, quotation_id: int):
    quotation = quotation_service.get_quotation(session, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")
    return quotation


def _get_version_or_404(session: Session, version_id: int):
    version = quotation_service.get_quotation_version(session, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation version not found.")
    return version


@router.get("/quotations", response_model=list[QuotationVersionRead])
def list_quotations(
    search: str | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.view")),
) -> list[QuotationVersionRead]:
    return list(quotation_service.list_quotation_versions(session, search=search))


@router.get("/quotations/{quotation_id}", response_model=QuotationRead)
def get_quotation(
    quotation_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.view")),
) -> QuotationRead:
    return _get_quotation_or_404(session, quotation_id)


@router.get("/quotations/{quotation_id}/versions", response_model=list[QuotationVersionRead])
def list_quotation_versions(
    quotation_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.view")),
) -> list[QuotationVersionRead]:
    _get_quotation_or_404(session, quotation_id)
    return list(quotation_service.list_versions_for_quotation(session, quotation_id))


@router.post(
    "/projects/{project_id}/quotations",
    response_model=QuotationVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_quotation(
    project_id: int,
    payload: QuotationCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.create")),
) -> QuotationVersionRead:
    project = project_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    try:
        return quotation_service.create_quotation(session, project, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/quotations/{quotation_id}/revisions",
    response_model=QuotationVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_quotation_revision(
    quotation_id: int,
    payload: QuotationRevisionCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.create")),
) -> QuotationVersionRead:
    quotation = _get_quotation_or_404(session, quotation_id)
    try:
        return quotation_service.create_quotation_revision(session, quotation, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/quotation-versions/{version_id}", response_model=QuotationVersionRead)
def get_quotation_version(
    version_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.view")),
) -> QuotationVersionRead:
    return _get_version_or_404(session, version_id)


@router.get("/quotation-versions/{version_id}/boq-lines", response_model=list[BOQLineItemRead])
def list_boq_lines(
    version_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.view")),
) -> list[BOQLineItemRead]:
    version = _get_version_or_404(session, version_id)
    return list(quotation_service.list_boq_line_items(session, version))


@router.post("/quotation-versions/{version_id}/submit", response_model=QuotationVersionRead)
def submit_quotation_version(
    version_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.submit")),
) -> QuotationVersionRead:
    version = _get_version_or_404(session, version_id)
    return quotation_service.mark_submitted(session, version)


@router.post("/quotation-versions/{version_id}/lose", response_model=QuotationVersionRead)
def lose_quotation_version(
    version_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.edit")),
) -> QuotationVersionRead:
    version = _get_version_or_404(session, version_id)
    return quotation_service.mark_lost(session, version)


@router.post("/quotation-versions/{version_id}/withdraw", response_model=QuotationVersionRead)
def withdraw_quotation_version(
    version_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.edit")),
) -> QuotationVersionRead:
    version = _get_version_or_404(session, version_id)
    return quotation_service.mark_withdrawn(session, version)


@router.post("/quotation-versions/{version_id}/award", response_model=QuotationVersionRead)
def award_quotation_version(
    version_id: int,
    payload: QuotationAward,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("quotations.approve")),
) -> QuotationVersionRead:
    version = _get_version_or_404(session, version_id)
    try:
        return quotation_service.mark_awarded(session, version, contract_value=payload.contract_value)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
