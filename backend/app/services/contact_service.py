"""Contact CRUD -- a person at a client's organization.

Mirrors `client_service.py`'s shape and validation style.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Client, Contact
from app.services.errors import ValidationError

__all__ = ["ValidationError", "list_contacts", "get_contact", "create_contact", "update_contact"]


def list_contacts(session: Session, *, client_id: int | None = None) -> list[Contact]:
    stmt = select(Contact).where(Contact.is_deleted.is_(False))
    if client_id is not None:
        stmt = stmt.where(Contact.client_id == client_id)
    stmt = stmt.order_by(Contact.full_name)
    return list(session.execute(stmt).scalars().all())


def get_contact(session: Session, contact_id: int) -> Contact | None:
    contact = session.get(Contact, contact_id)
    if contact is None or contact.is_deleted:
        return None
    return contact


def _validate_client(session: Session, client_id: int) -> None:
    client = session.get(Client, client_id)
    if client is None or client.is_deleted:
        raise ValidationError("Select a valid customer.")


def create_contact(
    session: Session,
    *,
    client_id: int,
    full_name: str,
    job_title: str | None = None,
    department: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    is_primary: bool = False,
    notes: str | None = None,
) -> Contact:
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationError("Contact name is required.")
    _validate_client(session, client_id)

    contact = Contact(
        client_id=client_id,
        full_name=full_name,
        job_title=(job_title or "").strip() or None,
        department=(department or "").strip() or None,
        phone=(phone or "").strip() or None,
        email=(email or "").strip() or None,
        is_primary=is_primary,
        notes=(notes or "").strip() or None,
    )
    session.add(contact)
    session.flush()
    return contact


def update_contact(
    session: Session,
    contact: Contact,
    *,
    client_id: int,
    full_name: str,
    job_title: str | None = None,
    department: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    is_primary: bool = False,
    notes: str | None = None,
) -> Contact:
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationError("Contact name is required.")
    _validate_client(session, client_id)

    contact.client_id = client_id
    contact.full_name = full_name
    contact.job_title = (job_title or "").strip() or None
    contact.department = (department or "").strip() or None
    contact.phone = (phone or "").strip() or None
    contact.email = (email or "").strip() or None
    contact.is_primary = is_primary
    contact.notes = (notes or "").strip() or None
    session.flush()
    return contact
