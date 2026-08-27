"""Vendor (supplier/subcontractor) CRUD.

Mirrors `client_service.py` deliberately -- same shape, same validation
style. See `app/models/vendor.py` for why suppliers and subcontractors
share one table (a `vendor_type` discriminator) rather than two.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DEFAULT_CURRENCY, Currency, VendorType
from app.models import Vendor
from app.services.errors import ValidationError

__all__ = ["ValidationError", "list_vendors", "get_vendor", "create_vendor", "update_vendor"]


def list_vendors(session: Session, *, search: str | None = None) -> list[Vendor]:
    stmt = select(Vendor).where(Vendor.is_deleted.is_(False)).order_by(Vendor.name)
    if search:
        stmt = stmt.where(Vendor.name.ilike(f"%{search}%"))
    return list(session.execute(stmt).scalars().all())


def get_vendor(session: Session, vendor_id: int) -> Vendor | None:
    vendor = session.get(Vendor, vendor_id)
    if vendor is None or vendor.is_deleted:
        return None
    return vendor


def create_vendor(
    session: Session,
    *,
    name: str,
    vendor_type: VendorType = VendorType.SUPPLIER,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    tax_number: str | None = None,
    default_currency: Currency = DEFAULT_CURRENCY,
    payment_terms: str | None = None,
    is_active: bool = True,
    notes: str | None = None,
) -> Vendor:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Vendor name is required.")

    vendor = Vendor(
        name=name,
        vendor_type=vendor_type,
        contact_name=(contact_name or "").strip() or None,
        contact_email=(contact_email or "").strip() or None,
        contact_phone=(contact_phone or "").strip() or None,
        tax_number=(tax_number or "").strip() or None,
        default_currency=default_currency,
        payment_terms=(payment_terms or "").strip() or None,
        is_active=is_active,
        notes=(notes or "").strip() or None,
    )
    session.add(vendor)
    session.flush()
    return vendor


def update_vendor(
    session: Session,
    vendor: Vendor,
    *,
    name: str,
    vendor_type: VendorType = VendorType.SUPPLIER,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    tax_number: str | None = None,
    default_currency: Currency = DEFAULT_CURRENCY,
    payment_terms: str | None = None,
    is_active: bool = True,
    notes: str | None = None,
) -> Vendor:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Vendor name is required.")

    vendor.name = name
    vendor.vendor_type = vendor_type
    vendor.contact_name = (contact_name or "").strip() or None
    vendor.contact_email = (contact_email or "").strip() or None
    vendor.contact_phone = (contact_phone or "").strip() or None
    vendor.tax_number = (tax_number or "").strip() or None
    vendor.default_currency = default_currency
    vendor.payment_terms = (payment_terms or "").strip() or None
    vendor.is_active = is_active
    vendor.notes = (notes or "").strip() or None
    session.flush()
    return vendor
