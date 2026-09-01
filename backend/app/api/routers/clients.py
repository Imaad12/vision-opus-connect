"""Customers -- the frontend's `customers` module, backed by the
existing `Client` model and `client_service`.

Permission names below are copied verbatim from the frontend's
`app_permission` enum (`customers.view/create/edit/delete`) so the two
systems share one vocabulary instead of a second one drifting alongside
it -- see the permission-string mismatch already found and fixed in
`purchase-orders.tsx`/`approvals.tsx` for why that matters.

Known gap: the frontend's `customers_select`/`customers_update` RLS also
scopes non-full-scope users to rows they own or created
(`owner_id`/`created_by`). `Client` has no such columns yet, so every
caller who passes the `customers.view`/`customers.edit` permission check
currently sees/edits every customer, not just their own. That is a real
scope gap, not a rewrite of the permission model -- it's called out here
and in API_ARCHITECTURE.md rather than silently assumed away.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas import ClientCreate, ClientRead, ClientUpdate
from app.services import client_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientRead])
def list_clients(
    search: str | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("customers.view")),
) -> list[ClientRead]:
    return list(client_service.list_clients(session, search=search))


@router.get("/{client_id}", response_model=ClientRead)
def get_client(
    client_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("customers.view")),
) -> ClientRead:
    client = client_service.get_client(session, client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")
    return client


@router.post("", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("customers.create")),
) -> ClientRead:
    try:
        return client_service.create_client(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{client_id}", response_model=ClientRead)
def update_client(
    client_id: int,
    payload: ClientUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("customers.edit")),
) -> ClientRead:
    client = client_service.get_client(session, client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")
    try:
        return client_service.update_client(session, client, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
