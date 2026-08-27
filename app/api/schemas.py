"""Pydantic request/response models for the API layer.

Kept separate from `app/models` (the SQLAlchemy ORM layer) deliberately:
these describe the wire format, not the storage format, and are allowed
to diverge from it (e.g. hiding soft-delete bookkeeping columns) without
that being a database migration.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Currency


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    legal_name: str | None
    trade_license_number: str | None
    default_currency: Currency
    address: str | None
    notes: str | None


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    address: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ClientCreate(BaseModel):
    name: str = Field(min_length=1)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    notes: str | None = None


class ClientUpdate(ClientCreate):
    pass
