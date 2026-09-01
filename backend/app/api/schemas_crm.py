"""Pydantic schemas for the CRM domain: Contact, Lead."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Currency, LeadSource, LeadStatus


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    full_name: str
    job_title: str | None
    department: str | None
    phone: str | None
    email: str | None
    is_primary: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ContactCreate(BaseModel):
    client_id: int
    full_name: str = Field(min_length=1)
    job_title: str | None = None
    department: str | None = None
    phone: str | None = None
    email: str | None = None
    is_primary: bool = False
    notes: str | None = None


class ContactUpdate(ContactCreate):
    pass


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    client_id: int | None
    contact_id: int | None
    source: LeadSource | None
    status: LeadStatus
    estimated_value: Decimal | None
    currency: Currency
    probability: int | None
    expected_close_date: date | None
    owner_id: str | None
    description: str | None
    lost_reason: str | None
    converted_project_id: int | None
    created_at: datetime
    updated_at: datetime


class LeadCreate(BaseModel):
    title: str = Field(min_length=1)
    client_id: int | None = None
    contact_id: int | None = None
    source: LeadSource | None = None
    status: LeadStatus = LeadStatus.NEW
    estimated_value: Decimal | None = None
    currency: Currency = Currency.AED
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    owner_id: str | None = None
    description: str | None = None
    lost_reason: str | None = None
    converted_project_id: int | None = None


class LeadUpdate(LeadCreate):
    pass
