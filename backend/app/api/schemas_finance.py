"""Pydantic schemas for the Finance domain: Invoice, Payment, Expense
(ActualCost), and the CostCategory lookup. Kept separate from
`schemas.py` the same way `schemas_procurement.py` is."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import CostPaymentStatus, Currency, InvoiceDirection, InvoiceStatus, PaymentMethod


class CostCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str | None


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    direction: InvoiceDirection
    client_id: int | None
    vendor_id: int | None
    invoice_number: str | None
    status: InvoiceStatus
    amount: Decimal
    tax_amount: Decimal | None
    retention_amount: Decimal | None
    currency: Currency
    issued_date: date | None
    due_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    amount_paid: Decimal = Decimal("0.00")


class InvoiceCreate(BaseModel):
    project_id: int
    direction: InvoiceDirection
    client_id: int | None = None
    vendor_id: int | None = None
    invoice_number: str | None = None
    amount: Decimal
    tax_amount: Decimal | None = None
    retention_amount: Decimal | None = None
    currency: Currency = Currency.AED
    issued_date: date | None = None
    due_date: date | None = None
    notes: str | None = None


class InvoiceUpdate(InvoiceCreate):
    status: InvoiceStatus | None = None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    amount: Decimal
    currency: Currency
    paid_date: date
    method: PaymentMethod | None
    reference: str | None
    is_retention_release: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class PaymentCreate(BaseModel):
    invoice_id: int
    amount: Decimal
    paid_date: date
    currency: Currency = Currency.AED
    method: PaymentMethod | None = None
    reference: str | None = None
    is_retention_release: bool = False
    notes: str | None = None


class ExpenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    cost_category_id: int
    vendor_id: int | None
    reference_number: str | None
    description: str | None
    amount: Decimal
    tax_amount: Decimal | None
    is_tax_recoverable: bool
    currency: Currency
    payment_status: CostPaymentStatus
    incurred_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ExpenseCreate(BaseModel):
    project_id: int
    cost_category_id: int
    vendor_id: int | None = None
    reference_number: str | None = None
    description: str | None = None
    amount: Decimal = Field(ge=0)
    tax_amount: Decimal | None = None
    is_tax_recoverable: bool = True
    currency: Currency = Currency.AED
    payment_status: CostPaymentStatus = CostPaymentStatus.UNPAID
    incurred_date: date | None = None
    notes: str | None = None


class ExpenseUpdate(ExpenseCreate):
    pass
