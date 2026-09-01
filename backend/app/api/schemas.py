"""Pydantic request/response models for the API layer.

Kept separate from `app/models` (the SQLAlchemy ORM layer) deliberately:
these describe the wire format, not the storage format, and are allowed
to diverge from it (e.g. hiding soft-delete bookkeeping columns) without
that being a database migration.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ContractStatus, Currency, ProjectStatus, QuotationStatus, VendorType


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


class VendorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vendor_type: VendorType
    name: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    tax_number: str | None
    default_currency: Currency
    payment_terms: str | None
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class VendorCreate(BaseModel):
    name: str = Field(min_length=1)
    vendor_type: VendorType = VendorType.SUPPLIER
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    tax_number: str | None = None
    default_currency: Currency = Currency.AED
    payment_terms: str | None = None
    is_active: bool = True
    notes: str | None = None


class VendorUpdate(VendorCreate):
    pass


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    client_id: int
    name: str
    project_code: str | None
    description: str | None
    status: ProjectStatus
    start_date: date | None
    planned_completion_date: date | None
    actual_completion_date: date | None
    award_date: date | None
    contract_value: Decimal | None
    contract_currency: Currency
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    client_id: int
    project_code: str | None = None
    description: str | None = None
    status: ProjectStatus = ProjectStatus.LEAD
    currency: Currency = Currency.AED
    start_date: date | None = None
    planned_completion_date: date | None = None
    actual_completion_date: date | None = None
    notes: str | None = None


class ProjectUpdate(ProjectCreate):
    pass


class ClientSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    project_code: str | None
    client: ClientSummary


class QuotationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    reference_number: str | None
    title: str | None
    project: ProjectSummary


class QuotationVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quotation_id: int
    version_number: int
    status: QuotationStatus
    quoted_value: Decimal | None
    currency: Currency
    issued_date: date | None
    valid_until: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    quotation: QuotationRead


class QuotationCreate(BaseModel):
    reference_number: str | None = None
    title: str | None = None
    quoted_value: Decimal | None = None
    currency: Currency = Currency.AED
    issued_date: date | None = None
    valid_until: date | None = None
    notes: str | None = None


class QuotationRevisionCreate(BaseModel):
    quoted_value: Decimal | None = None
    currency: Currency = Currency.AED
    issued_date: date | None = None
    valid_until: date | None = None
    notes: str | None = None


class QuotationAward(BaseModel):
    contract_value: Decimal = Field(gt=0)


class BOQLineItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_number: str | None
    description: str
    unit: str | None
    quantity: Decimal | None
    unit_rate: Decimal | None
    total: Decimal | None
    currency: Currency


class ContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    project: ProjectSummary
    quotation_version_id: int
    contract_number: str | None
    value: Decimal
    currency: Currency
    status: ContractStatus
    signed_date: date | None
    start_date: date | None
    end_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ContractCreate(BaseModel):
    contract_number: str | None = None
    signed_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None
