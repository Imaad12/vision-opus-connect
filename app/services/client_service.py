"""Client CRUD.

Deliberately minimal — this is not a CRM. It exists so the UI (and project
creation) never issues SQL directly.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Client
from app.services.errors import ValidationError

__all__ = ["ValidationError", "list_clients", "get_client", "create_client", "update_client"]


def list_clients(session: Session, *, search: str | None = None) -> list[Client]:
    stmt = select(Client).where(Client.is_deleted.is_(False)).order_by(Client.name)
    if search:
        stmt = stmt.where(Client.name.ilike(f"%{search}%"))
    return list(session.execute(stmt).scalars().all())


def get_client(session: Session, client_id: int) -> Client | None:
    client = session.get(Client, client_id)
    if client is None or client.is_deleted:
        return None
    return client


def create_client(
    session: Session,
    *,
    name: str,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    address: str | None = None,
    notes: str | None = None,
) -> Client:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Client name is required.")

    client = Client(
        name=name,
        contact_name=(contact_name or "").strip() or None,
        contact_email=(contact_email or "").strip() or None,
        contact_phone=(contact_phone or "").strip() or None,
        address=(address or "").strip() or None,
        notes=(notes or "").strip() or None,
    )
    session.add(client)
    session.flush()
    return client


def update_client(
    session: Session,
    client: Client,
    *,
    name: str,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    address: str | None = None,
    notes: str | None = None,
) -> Client:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Client name is required.")

    client.name = name
    client.contact_name = (contact_name or "").strip() or None
    client.contact_email = (contact_email or "").strip() or None
    client.contact_phone = (contact_phone or "").strip() or None
    client.address = (address or "").strip() or None
    client.notes = (notes or "").strip() or None
    session.flush()
    return client
