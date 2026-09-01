"""Purchase Request CRUD and approval lifecycle.

A `PurchaseRequest` is the internal ask ("we need X for project Y")
raised before a `PurchaseOrder` exists. It never becomes a PO
automatically -- procurement raises a PO referencing an approved
request explicitly (`PurchaseOrder.purchase_request_id`), exactly like
awarding a quotation is never automatic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DEFAULT_CURRENCY, Currency, PurchaseRequestStatus
from app.models import Project, PurchaseRequest, Vendor
from app.services.errors import ValidationError

__all__ = [
    "ValidationError",
    "list_purchase_requests",
    "get_purchase_request",
    "create_purchase_request",
    "submit_purchase_request",
    "approve_purchase_request",
    "reject_purchase_request",
]


def list_purchase_requests(session: Session, *, project_id: int | None = None) -> list[PurchaseRequest]:
    stmt = select(PurchaseRequest).where(PurchaseRequest.is_deleted.is_(False))
    if project_id is not None:
        stmt = stmt.where(PurchaseRequest.project_id == project_id)
    stmt = stmt.order_by(PurchaseRequest.id.desc())
    return list(session.execute(stmt).scalars().all())


def get_purchase_request(session: Session, request_id: int) -> PurchaseRequest | None:
    request = session.get(PurchaseRequest, request_id)
    if request is None or request.is_deleted:
        return None
    return request


def create_purchase_request(
    session: Session,
    *,
    project_id: int,
    items_description: str,
    vendor_id: int | None = None,
    requested_amount: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    requested_by: str | None = None,
    requested_date: date | None = None,
    notes: str | None = None,
) -> PurchaseRequest:
    items_description = (items_description or "").strip()
    if not items_description:
        raise ValidationError("Describe what is being requested.")

    project = session.get(Project, project_id)
    if project is None or project.is_deleted:
        raise ValidationError("Select a valid project.")

    if vendor_id is not None:
        vendor = session.get(Vendor, vendor_id)
        if vendor is None or vendor.is_deleted:
            raise ValidationError("Select a valid vendor.")

    request = PurchaseRequest(
        project_id=project_id,
        vendor_id=vendor_id,
        items_description=items_description,
        requested_amount=requested_amount,
        currency=currency,
        requested_by=(requested_by or "").strip() or None,
        requested_date=requested_date,
        notes=(notes or "").strip() or None,
    )
    session.add(request)
    session.flush()
    return request


def submit_purchase_request(session: Session, request: PurchaseRequest) -> PurchaseRequest:
    if request.status != PurchaseRequestStatus.DRAFT:
        raise ValidationError("Only a draft purchase request can be submitted.")
    request.status = PurchaseRequestStatus.SUBMITTED
    session.flush()
    return request


def approve_purchase_request(
    session: Session, request: PurchaseRequest, *, approved_by: str | None = None
) -> PurchaseRequest:
    if request.status != PurchaseRequestStatus.SUBMITTED:
        raise ValidationError("Only a submitted purchase request can be approved.")
    request.status = PurchaseRequestStatus.APPROVED
    request.approved_by = (approved_by or "").strip() or None
    request.approved_at = datetime.now(UTC).replace(tzinfo=None)
    session.flush()
    return request


def reject_purchase_request(session: Session, request: PurchaseRequest) -> PurchaseRequest:
    if request.status != PurchaseRequestStatus.SUBMITTED:
        raise ValidationError("Only a submitted purchase request can be rejected.")
    request.status = PurchaseRequestStatus.REJECTED
    session.flush()
    return request
