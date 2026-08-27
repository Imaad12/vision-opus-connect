"""Leads -- the frontend's `leads` module. Permission names copied
verbatim from the frontend's real `app_permission` enum
(`leads.view/create/edit`) -- there is deliberately no `leads.delete` in
that enum (see `app/models/lead.py`: winning/losing a lead is recorded via
`status`, not deletion), so no remove endpoint or button is wired here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_crm import LeadCreate, LeadRead, LeadUpdate
from app.services import lead_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=list[LeadRead])
def list_leads(
    session: Session = Depends(get_db),
    _user=Depends(require_permission("leads.view")),
) -> list[LeadRead]:
    return list(lead_service.list_leads(session))


@router.get("/{lead_id}", response_model=LeadRead)
def get_lead(
    lead_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("leads.view")),
) -> LeadRead:
    lead = lead_service.get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    return lead


@router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: LeadCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("leads.create")),
) -> LeadRead:
    try:
        return lead_service.create_lead(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("leads.edit")),
) -> LeadRead:
    lead = lead_service.get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    try:
        return lead_service.update_lead(session, lead, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
