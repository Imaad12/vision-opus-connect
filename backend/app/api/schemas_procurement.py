"""Pydantic request/response models for the procurement domain (Purchase
Requests, Supplier Purchase Orders, Receipts). Kept in its own module,
separate from `app/api/schemas.py`, purely to keep that file from growing
without bound -- see that module's docstring for the general rationale
(wire format, not storage format).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas import ClientSummary, ProjectSummary
from app.core.enums import Currency, PurchaseOrderStatus, PurchaseRequestStatus, ReceiptStatus


class VendorSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class PurchaseRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    project: ProjectSummary
    vendor_id: int | None
    vendor: VendorSummary | None
    requested_by: str | None
    items_description: str
    requested_amount: Decimal | None
    currency: Currency
    status: PurchaseRequestStatus
    requested_date: date | None
    approved_by: str | None
    approved_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class PurchaseRequestCreate(BaseModel):
    project_id: int
    vendor_id: int | None = None
    items_description: str = Field(min_length=1)
    requested_amount: Decimal | None = None
    currency: Currency = Currency.SAR
    requested_by: str | None = None
    requested_date: date | None = None
    notes: str | None = None


class PurchaseOrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    description: str
    unit: str | None
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    received_quantity: Decimal


class PurchaseOrderLineInput(BaseModel):
    description: str = Field(min_length=1)
    unit: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_number: str
    vendor_id: int
    vendor: VendorSummary
    project_id: int
    project: ProjectSummary
    purchase_request_id: int | None
    order_date: date | None
    status: PurchaseOrderStatus
    currency: Currency
    vat_rate: Decimal
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    notes: str | None
    lines: list[PurchaseOrderLineRead]
    created_at: datetime
    updated_at: datetime


class PurchaseOrderCreate(BaseModel):
    po_number: str = Field(min_length=1)
    vendor_id: int
    project_id: int
    purchase_request_id: int | None = None
    order_date: date | None = None
    currency: Currency = Currency.SAR
    vat_rate: Decimal = Decimal("15.00")
    notes: str | None = None


class PurchaseOrderLinesUpdate(BaseModel):
    lines: list[PurchaseOrderLineInput]


class ReceiptLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    purchase_order_line_id: int
    quantity_received: Decimal


class ReceiptLineInput(BaseModel):
    purchase_order_line_id: int
    quantity_received: Decimal = Field(gt=0)


class ReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    purchase_order_id: int
    project_id: int
    receipt_date: date
    status: ReceiptStatus
    received_by: str | None
    notes: str | None
    lines: list[ReceiptLineRead]
    created_at: datetime
    updated_at: datetime


class ReceiptCreate(BaseModel):
    receipt_date: date
    lines: list[ReceiptLineInput] = Field(min_length=1)
    received_by: str | None = None
    notes: str | None = None


__all__ = [
    "ClientSummary",
    "VendorSummary",
    "PurchaseRequestRead",
    "PurchaseRequestCreate",
    "PurchaseOrderLineRead",
    "PurchaseOrderLineInput",
    "PurchaseOrderRead",
    "PurchaseOrderCreate",
    "PurchaseOrderLinesUpdate",
    "ReceiptLineRead",
    "ReceiptLineInput",
    "ReceiptRead",
    "ReceiptCreate",
]
