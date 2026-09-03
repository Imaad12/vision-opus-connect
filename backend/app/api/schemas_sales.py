"""Pydantic request/response models for the commercial/sales pipeline's
Client PO (award-evidence) surface -- kept separate from
`schemas_procurement.py` (Supplier Purchase Orders) on purpose: those are
two unrelated domains that happen to share the word "purchase order"
(see `app.models.client_award_evidence`'s own module docstring, and
`app.api.routers.purchase_orders`'s docstring on the same distinction).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas import ProjectSummary, QuotationVersionRead
from app.core.enums import Currency


class ClientAwardEvidenceDocumentRead(BaseModel):
    """The original client PO file this record was confirmed from (via
    the OCR-import pipeline), or was later attached to (a manually
    recorded award with a document uploaded after the fact) -- `None`
    when no document has ever been linked. Mirrors the same
    "traceable back to the original file" guarantee historical
    quotations already have (see `app.models.import_staging.
    ImportedDocument`); this never re-implements storage or hashing,
    only reads the existing `ImportedDocument` row."""

    id: int
    filename: str


class ClientAwardEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quotation_id: int
    po_reference_number: str
    po_date: date | None
    net_value: Decimal | None
    tax_value: Decimal | None
    gross_value: Decimal | None
    currency: Currency
    notes: str | None
    awarded_quotation_version_id: int | None
    awarded_quotation_version: QuotationVersionRead | None
    # Denormalized onto the response (not the model) purely for the "POs
    # Awarded by Client" table -- reached in one query via
    # `client_award_evidence_service.list_client_award_evidence`'s own
    # joins, never a second copy of the data.
    project: ProjectSummary
    quotation_reference_number: str | None
    quoted_value: Decimal | None
    variance: Decimal | None = Field(
        default=None,
        description=(
            "net_value - quoted_value, when both are known. Never persisted -- the quotation's own "
            "quoted_value is never overwritten by the awarded value, they are always shown side by "
            "side and compared at read time."
        ),
    )
    #: "imported" if this record was confirmed via the OCR/import staging
    #: pipeline, "manual" if a reviewer entered it directly on the
    #: Quotations screen -- see `ImportedDocument.resulting_client_award_evidence_id`.
    source: str
    document: ClientAwardEvidenceDocumentRead | None
    #: True once a `Contract` exists for this award's project -- the
    #: existing `contracts` domain, not a second status value invented
    #: here (see `app.services.contract_service`).
    contracted: bool
    created_at: datetime
    updated_at: datetime


class ClientAwardEvidenceCreate(BaseModel):
    """`POST /quotations/{quotation_id}/client-po` -- record a client
    award/PO by hand. Every value is independent of the quotation's own
    `quoted_value`; see `ClientAwardEvidenceRead.variance`."""

    po_reference_number: str = Field(min_length=1)
    po_date: date | None = None
    net_value: Decimal | None = Field(default=None, ge=0)
    tax_value: Decimal | None = Field(default=None, ge=0)
    gross_value: Decimal | None = Field(default=None, ge=0)
    currency: Currency | None = None
    notes: str | None = None
