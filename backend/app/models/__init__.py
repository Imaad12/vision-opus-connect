"""SQLAlchemy ORM models.

Importing this package registers every model on `Base.metadata`, which is
what `init_db.create_all()` and Alembic's autogeneration rely on.
"""

from app.models.app_user import AppUser
from app.models.boq import BOQ, BOQLineItem
from app.models.client import Client
from app.models.company import Company
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.cost import ActualCost, EstimatedCost, EstimateRevision
from app.models.document import GoogleDriveDocument
from app.models.employee import Employee, PayrollRecord
from app.models.import_staging import (
    ImportAuditLogEntry,
    ImportBatch,
    ImportedBoqLineCandidate,
    ImportedDocument,
    ImportedDocumentSegment,
    ImportedClientAwardEvidenceCandidate,
    ImportedQuotationCandidate,
    ImportJob,
)
from app.models.invoice import Invoice, Payment
from app.models.lead import Lead
from app.models.lookups import CostCategory, Trade
from app.models.project import Project, ProjectStatusHistory
from app.models.client_award_evidence import ClientAwardEvidence
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.purchase_request import PurchaseRequest
from app.models.quotation import Quotation, QuotationVersion
from app.models.receipt import Receipt, ReceiptLine
from app.models.variation import ProjectVariation
from app.models.vendor import Vendor

__all__ = [
    "AppUser",
    "BOQ",
    "BOQLineItem",
    "Client",
    "Company",
    "Contact",
    "Contract",
    "ActualCost",
    "EstimatedCost",
    "EstimateRevision",
    "Employee",
    "PayrollRecord",
    "GoogleDriveDocument",
    "ImportAuditLogEntry",
    "ImportBatch",
    "ImportedBoqLineCandidate",
    "ImportedDocument",
    "ImportedDocumentSegment",
    "ImportedClientAwardEvidenceCandidate",
    "ImportedQuotationCandidate",
    "ImportJob",
    "Invoice",
    "Payment",
    "Lead",
    "CostCategory",
    "Trade",
    "Project",
    "ProjectStatusHistory",
    "ClientAwardEvidence",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "PurchaseRequest",
    "Quotation",
    "QuotationVersion",
    "Receipt",
    "ReceiptLine",
    "ProjectVariation",
    "Vendor",
]
