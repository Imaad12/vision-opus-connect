"""Purchase Requests -- backed entirely by `purchase_request_service`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_procurement import PurchaseRequestCreate, PurchaseRequestRead
from app.services import purchase_request_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/purchase-requests", tags=["procurement"])


def _get_or_404(session: Session, request_id: int):
    request = purchase_request_service.get_purchase_request(session, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase request not found.")
    return request


@router.get("", response_model=list[PurchaseRequestRead])
def list_purchase_requests(
    project_id: int | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.request")),
) -> list[PurchaseRequestRead]:
    return list(purchase_request_service.list_purchase_requests(session, project_id=project_id))


@router.get("/{request_id}", response_model=PurchaseRequestRead)
def get_purchase_request(
    request_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.request")),
) -> PurchaseRequestRead:
    return _get_or_404(session, request_id)


@router.post("", response_model=PurchaseRequestRead, status_code=status.HTTP_201_CREATED)
def create_purchase_request(
    payload: PurchaseRequestCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.request")),
) -> PurchaseRequestRead:
    try:
        return purchase_request_service.create_purchase_request(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{request_id}/submit", response_model=PurchaseRequestRead)
def submit_purchase_request(
    request_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.request")),
) -> PurchaseRequestRead:
    request = _get_or_404(session, request_id)
    try:
        return purchase_request_service.submit_purchase_request(session, request)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{request_id}/approve", response_model=PurchaseRequestRead)
def approve_purchase_request(
    request_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_approve")),
) -> PurchaseRequestRead:
    request = _get_or_404(session, request_id)
    try:
        return purchase_request_service.approve_purchase_request(session, request)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{request_id}/reject", response_model=PurchaseRequestRead)
def reject_purchase_request(
    request_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("purchasing.po_approve")),
) -> PurchaseRequestRead:
    request = _get_or_404(session, request_id)
    try:
        return purchase_request_service.reject_purchase_request(session, request)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
