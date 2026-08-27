"""Lead CRUD -- the pre-project sales pipeline.

Deliberately never touches `Project`: converting a won lead into a
project is a manual, separate action (create the project, then set
`Lead.converted_project_id`), exactly like awarding a quotation is a
distinct step from creating the `Contract` it produces.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DEFAULT_CURRENCY, Currency, LeadSource, LeadStatus
from app.models import Client, Contact, Lead, Project
from app.services.errors import ValidationError

__all__ = ["ValidationError", "list_leads", "get_lead", "create_lead", "update_lead"]


def list_leads(session: Session, *, status: LeadStatus | None = None) -> list[Lead]:
    stmt = select(Lead).where(Lead.is_deleted.is_(False))
    if status is not None:
        stmt = stmt.where(Lead.status == status)
    stmt = stmt.order_by(Lead.id.desc())
    return list(session.execute(stmt).scalars().all())


def get_lead(session: Session, lead_id: int) -> Lead | None:
    lead = session.get(Lead, lead_id)
    if lead is None or lead.is_deleted:
        return None
    return lead


def _validate_refs(
    session: Session,
    *,
    client_id: int | None,
    contact_id: int | None,
    converted_project_id: int | None,
    probability: int | None,
) -> None:
    if client_id is not None:
        client = session.get(Client, client_id)
        if client is None or client.is_deleted:
            raise ValidationError("Select a valid customer.")
    if contact_id is not None:
        contact = session.get(Contact, contact_id)
        if contact is None or contact.is_deleted:
            raise ValidationError("Select a valid contact.")
    if converted_project_id is not None:
        project = session.get(Project, converted_project_id)
        if project is None or project.is_deleted:
            raise ValidationError("Select a valid project.")
    if probability is not None and not (0 <= probability <= 100):
        raise ValidationError("Win probability must be between 0 and 100.")


def create_lead(
    session: Session,
    *,
    title: str,
    client_id: int | None = None,
    contact_id: int | None = None,
    source: LeadSource | None = None,
    status: LeadStatus = LeadStatus.NEW,
    estimated_value: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    probability: int | None = None,
    expected_close_date: date | None = None,
    owner_id: str | None = None,
    description: str | None = None,
    lost_reason: str | None = None,
    converted_project_id: int | None = None,
) -> Lead:
    title = (title or "").strip()
    if not title:
        raise ValidationError("Opportunity title is required.")
    _validate_refs(
        session,
        client_id=client_id,
        contact_id=contact_id,
        converted_project_id=converted_project_id,
        probability=probability,
    )

    lead = Lead(
        title=title,
        client_id=client_id,
        contact_id=contact_id,
        source=source,
        status=status,
        estimated_value=estimated_value,
        currency=currency,
        probability=probability,
        expected_close_date=expected_close_date,
        owner_id=(owner_id or "").strip() or None,
        description=(description or "").strip() or None,
        lost_reason=(lost_reason or "").strip() or None,
        converted_project_id=converted_project_id,
    )
    session.add(lead)
    session.flush()
    return lead


def update_lead(
    session: Session,
    lead: Lead,
    *,
    title: str,
    client_id: int | None = None,
    contact_id: int | None = None,
    source: LeadSource | None = None,
    status: LeadStatus = LeadStatus.NEW,
    estimated_value: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    probability: int | None = None,
    expected_close_date: date | None = None,
    owner_id: str | None = None,
    description: str | None = None,
    lost_reason: str | None = None,
    converted_project_id: int | None = None,
) -> Lead:
    title = (title or "").strip()
    if not title:
        raise ValidationError("Opportunity title is required.")
    _validate_refs(
        session,
        client_id=client_id,
        contact_id=contact_id,
        converted_project_id=converted_project_id,
        probability=probability,
    )

    lead.title = title
    lead.client_id = client_id
    lead.contact_id = contact_id
    lead.source = source
    lead.status = status
    lead.estimated_value = estimated_value
    lead.currency = currency
    lead.probability = probability
    lead.expected_close_date = expected_close_date
    lead.owner_id = (owner_id or "").strip() or None
    lead.description = (description or "").strip() or None
    lead.lost_reason = (lost_reason or "").strip() or None
    lead.converted_project_id = converted_project_id
    session.flush()
    return lead
