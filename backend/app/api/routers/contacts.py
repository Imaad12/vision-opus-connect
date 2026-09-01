"""Contacts -- the frontend's `contacts` module. Permission names copied
verbatim from the frontend's real `app_permission` enum
(`contacts.view/create/edit`) -- the page previously reused
`customers.*`, which works (those permissions exist) but gates contacts on
the wrong resource's grant."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_crm import ContactCreate, ContactRead, ContactUpdate
from app.services import contact_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactRead])
def list_contacts(
    client_id: int | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contacts.view")),
) -> list[ContactRead]:
    return list(contact_service.list_contacts(session, client_id=client_id))


@router.get("/{contact_id}", response_model=ContactRead)
def get_contact(
    contact_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contacts.view")),
) -> ContactRead:
    contact = contact_service.get_contact(session, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")
    return contact


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
def create_contact(
    payload: ContactCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contacts.create")),
) -> ContactRead:
    try:
        return contact_service.create_contact(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contacts.edit")),
) -> ContactRead:
    contact = contact_service.get_contact(session, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")
    try:
        return contact_service.update_contact(session, contact, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
