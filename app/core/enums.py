"""Shared enumerations.

These carry no dependency on SQLAlchemy, Qt, or pandas so they can be used
from `core`, `models`, `services`, and `ui` alike without pulling in any
particular framework.
"""

from __future__ import annotations

from enum import StrEnum


class Currency(StrEnum):
    """ISO-4217 currency codes in common use by the business.

    This is not an exhaustive ISO-4217 list. It covers the currencies the
    business actually deals with today; the underlying database column is a
    plain string, so supporting an additional currency later is a data
    change, not a schema migration.
    """

    AED = "AED"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    SAR = "SAR"


DEFAULT_CURRENCY = Currency.AED


class ProjectStatus(StrEnum):
    LEAD = "LEAD"
    TENDERING = "TENDERING"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    LOST = "LOST"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class QuotationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISED = "REVISED"
    WON = "WON"
    LOST = "LOST"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class VendorType(StrEnum):
    SUPPLIER = "SUPPLIER"
    SUBCONTRACTOR = "SUBCONTRACTOR"


class InvoiceDirection(StrEnum):
    CLIENT = "CLIENT"
    VENDOR = "VENDOR"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "BANK_TRANSFER"
    CHEQUE = "CHEQUE"
    CASH = "CASH"
    CARD = "CARD"
    OTHER = "OTHER"


class VariationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DocumentType(StrEnum):
    QUOTATION = "QUOTATION"
    BOQ = "BOQ"
    CONTRACT = "CONTRACT"
    INVOICE = "INVOICE"
    DRAWING = "DRAWING"
    PHOTO = "PHOTO"
    CORRESPONDENCE = "CORRESPONDENCE"
    OTHER = "OTHER"
