"""Integration tests for the ORM schema itself: constraints, defaults, and
the estimate/actual separation, exercised against a real (in-memory)
SQLite database rather than mocked."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import InvoiceDirection, QuotationStatus, VendorType
from app.models import (
    Client,
    Company,
    CostCategory,
    EstimatedCost,
    Invoice,
    Project,
    Quotation,
    QuotationVersion,
    Vendor,
)


def _make_project(session: Session) -> Project:
    company = Company(name="Vision Contracting LLC")
    client = Client(name="Acme Developers")
    session.add_all([company, client])
    session.flush()
    project = Project(company_id=company.id, client_id=client.id, name="Villa Renovation")
    session.add(project)
    session.flush()
    return project


def test_project_soft_delete_defaults_false(db_session: Session) -> None:
    project = _make_project(db_session)
    assert project.is_deleted is False
    assert project.deleted_at is None


def test_quotation_version_unique_per_quotation(db_session: Session) -> None:
    project = _make_project(db_session)
    quotation = Quotation(project_id=project.id)
    db_session.add(quotation)
    db_session.flush()

    db_session.add(QuotationVersion(quotation_id=quotation.id, version_number=1))
    db_session.flush()

    db_session.add(QuotationVersion(quotation_id=quotation.id, version_number=1))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_invoice_direction_check_constraint(db_session: Session) -> None:
    project = _make_project(db_session)
    vendor = Vendor(vendor_type=VendorType.SUPPLIER, name="Steel Co")
    db_session.add(vendor)
    db_session.flush()

    # CLIENT direction with a vendor_id (and no client_id) must be rejected.
    bad_invoice = Invoice(
        project_id=project.id,
        direction=InvoiceDirection.CLIENT,
        vendor_id=vendor.id,
        amount=Decimal("1000"),
    )
    db_session.add(bad_invoice)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_estimated_and_actual_costs_are_independent(db_session: Session) -> None:
    """Estimated and actual costs must be stored in separate tables/rows so
    one can never silently overwrite the other."""
    project = _make_project(db_session)
    quotation = Quotation(project_id=project.id)
    db_session.add(quotation)
    db_session.flush()
    qv = QuotationVersion(
        quotation_id=quotation.id,
        version_number=1,
        status=QuotationStatus.WON,
        quoted_value=Decimal("100000"),
    )
    category = CostCategory(name="Labor")
    db_session.add_all([qv, category])
    db_session.flush()

    estimated = EstimatedCost(
        project_id=project.id,
        quotation_version_id=qv.id,
        cost_category_id=category.id,
        amount=Decimal("70000"),
    )
    db_session.add(estimated)
    db_session.commit()

    assert estimated.amount == Decimal("70000")
    # Nothing about recording an EstimatedCost touches actual_costs at all;
    # the tables are entirely separate.
    from app.models import ActualCost

    assert db_session.query(ActualCost).count() == 0
