"""SQLAlchemy ORM models.

Importing this package registers every model on `Base.metadata`, which is
what `init_db.create_all()` and Alembic's autogeneration rely on.
"""

from app.models.boq import BOQ, BOQLineItem
from app.models.client import Client
from app.models.company import Company
from app.models.contract import Contract
from app.models.cost import ActualCost, EstimatedCost, EstimateRevision
from app.models.document import GoogleDriveDocument
from app.models.import_staging import (
    ImportAuditLogEntry,
    ImportedBoqLineCandidate,
    ImportedDocument,
    ImportedDocumentSegment,
    ImportedPurchaseOrderCandidate,
    ImportedQuotationCandidate,
)
from app.models.invoice import Invoice, Payment
from app.models.lookups import CostCategory, Trade
from app.models.project import Project, ProjectStatusHistory
from app.models.purchase_order import PurchaseOrder
from app.models.quotation import Quotation, QuotationVersion
from app.models.variation import ProjectVariation
from app.models.vendor import Vendor

__all__ = [
    "BOQ",
    "BOQLineItem",
    "Client",
    "Company",
    "Contract",
    "ActualCost",
    "EstimatedCost",
    "EstimateRevision",
    "GoogleDriveDocument",
    "ImportAuditLogEntry",
    "ImportedBoqLineCandidate",
    "ImportedDocument",
    "ImportedDocumentSegment",
    "ImportedPurchaseOrderCandidate",
    "ImportedQuotationCandidate",
    "Invoice",
    "Payment",
    "CostCategory",
    "Trade",
    "Project",
    "ProjectStatusHistory",
    "PurchaseOrder",
    "Quotation",
    "QuotationVersion",
    "ProjectVariation",
    "Vendor",
]
