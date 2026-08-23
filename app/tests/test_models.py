"""Integration tests for the ORM schema itself: constraints, defaults, and
the estimate/actual separation, exercised against a real (in-memory)
SQLite database rather than mocked."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import CostPaymentStatus, InvoiceDirection, QuotationStatus, VendorType
from app.models import (
    ActualCost,
    Client,
    Company,
    CostCategory,
    EstimatedCost,
    EstimateRevision,
    Invoice,
    Payment,
    Project,
    ProjectVariation,
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


def _make_client_invoice(session: Session, project: Project, **kwargs: Decimal) -> Invoice:
    client = Client(name="Acme Developers 2")
    session.add(client)
    session.flush()
    invoice = Invoice(
        project_id=project.id,
        direction=InvoiceDirection.CLIENT,
        client_id=client.id,
        amount=kwargs.pop("amount", Decimal("105000")),
        **kwargs,
    )
    session.add(invoice)
    return invoice


def test_invoice_tax_amount_within_range_is_accepted(db_session: Session) -> None:
    project = _make_project(db_session)
    invoice = _make_client_invoice(
        db_session, project, amount=Decimal("105000"), tax_amount=Decimal("5000")
    )
    db_session.commit()
    assert invoice.tax_amount == Decimal("5000")


def test_invoice_tax_amount_exceeding_amount_is_rejected(db_session: Session) -> None:
    project = _make_project(db_session)
    _make_client_invoice(db_session, project, amount=Decimal("1000"), tax_amount=Decimal("2000"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_invoice_negative_tax_on_positive_invoice_is_rejected(db_session: Session) -> None:
    project = _make_project(db_session)
    _make_client_invoice(db_session, project, amount=Decimal("1000"), tax_amount=Decimal("-50"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_invoice_credit_note_with_matching_negative_tax_is_accepted(db_session: Session) -> None:
    # A credit note reversing a prior invoice: both amount and tax are negative.
    project = _make_project(db_session)
    invoice = _make_client_invoice(
        db_session, project, amount=Decimal("-1050"), tax_amount=Decimal("-50")
    )
    db_session.commit()
    assert invoice.amount == Decimal("-1050")


def test_invoice_retention_amount_within_range_is_accepted(db_session: Session) -> None:
    project = _make_project(db_session)
    invoice = _make_client_invoice(
        db_session, project, amount=Decimal("100000"), retention_amount=Decimal("10000")
    )
    db_session.commit()
    assert invoice.retention_amount == Decimal("10000")


def test_invoice_retention_amount_exceeding_amount_is_rejected(db_session: Session) -> None:
    project = _make_project(db_session)
    _make_client_invoice(
        db_session, project, amount=Decimal("1000"), retention_amount=Decimal("5000")
    )
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
    assert db_session.query(ActualCost).count() == 0


def _make_cost_category(session: Session, name: str = "Materials") -> CostCategory:
    category = CostCategory(name=name)
    session.add(category)
    session.flush()
    return category


def test_estimated_cost_quantity_unit_rate_fields(db_session: Session) -> None:
    project = _make_project(db_session)
    category = _make_cost_category(db_session)
    estimated = EstimatedCost(
        project_id=project.id,
        cost_category_id=category.id,
        description="Cement bags",
        quantity=Decimal("100"),
        unit="bag",
        unit_rate=Decimal("25.50"),
        amount=Decimal("2550.00"),
        notes="Bulk order",
    )
    db_session.add(estimated)
    db_session.commit()

    assert estimated.quantity == Decimal("100")
    assert estimated.unit == "bag"
    assert estimated.unit_rate == Decimal("25.50")
    assert estimated.notes == "Bulk order"


def test_actual_cost_defaults(db_session: Session) -> None:
    project = _make_project(db_session)
    category = _make_cost_category(db_session, "Labour")
    actual = ActualCost(
        project_id=project.id,
        cost_category_id=category.id,
        amount=Decimal("10000"),
    )
    db_session.add(actual)
    db_session.commit()

    assert actual.is_tax_recoverable is True
    assert actual.payment_status == CostPaymentStatus.UNPAID
    assert actual.tax_amount is None


def test_actual_cost_tax_amount_exceeding_amount_is_rejected(db_session: Session) -> None:
    project = _make_project(db_session)
    category = _make_cost_category(db_session, "Equipment")
    actual = ActualCost(
        project_id=project.id,
        cost_category_id=category.id,
        amount=Decimal("1000"),
        tax_amount=Decimal("2000"),
    )
    db_session.add(actual)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_actual_cost_non_recoverable_tax_flag(db_session: Session) -> None:
    project = _make_project(db_session)
    category = _make_cost_category(db_session, "Subcontractors")
    actual = ActualCost(
        project_id=project.id,
        cost_category_id=category.id,
        amount=Decimal("10500"),
        tax_amount=Decimal("500"),
        is_tax_recoverable=False,
        reference_number="INV-2024-001",
        payment_status=CostPaymentStatus.PAID,
    )
    db_session.add(actual)
    db_session.commit()

    assert actual.is_tax_recoverable is False
    assert actual.reference_number == "INV-2024-001"
    assert actual.payment_status == CostPaymentStatus.PAID


def test_payment_retention_release_flag_defaults_false(db_session: Session) -> None:
    project = _make_project(db_session)
    invoice = _make_client_invoice(db_session, project, amount=Decimal("100000"))
    db_session.flush()
    payment = Payment(invoice_id=invoice.id, amount=Decimal("50000"), paid_date=date(2026, 1, 1))
    db_session.add(payment)
    db_session.commit()

    assert payment.is_retention_release is False


def test_payment_retention_release_flag_can_be_set(db_session: Session) -> None:
    project = _make_project(db_session)
    invoice = _make_client_invoice(
        db_session, project, amount=Decimal("100000"), retention_amount=Decimal("5000")
    )
    db_session.flush()
    release = Payment(
        invoice_id=invoice.id,
        amount=Decimal("5000"),
        paid_date=date(2026, 6, 1),
        is_retention_release=True,
    )
    db_session.add(release)
    db_session.commit()

    assert release.is_retention_release is True


def test_project_variation_negative_approved_value_is_allowed(db_session: Session) -> None:
    from app.core.enums import VariationStatus

    project = _make_project(db_session)
    variation = ProjectVariation(
        project_id=project.id,
        approved_value_change=Decimal("-25000"),
        status=VariationStatus.APPROVED,
    )
    db_session.add(variation)
    db_session.commit()

    assert variation.approved_value_change == Decimal("-25000")


def test_estimate_revision_unique_per_project(db_session: Session) -> None:
    project = _make_project(db_session)
    db_session.add(EstimateRevision(project_id=project.id, revision_number=1))
    db_session.commit()

    db_session.add(EstimateRevision(project_id=project.id, revision_number=1))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_estimate_revision_number_must_be_positive(db_session: Session) -> None:
    project = _make_project(db_session)
    db_session.add(EstimateRevision(project_id=project.id, revision_number=0))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_estimate_revision_only_one_final_per_project(db_session: Session) -> None:
    project = _make_project(db_session)
    db_session.add(EstimateRevision(project_id=project.id, revision_number=1, is_final=True))
    db_session.commit()

    db_session.add(EstimateRevision(project_id=project.id, revision_number=2, is_final=True))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_estimate_revision_multiple_non_final_revisions_allowed(db_session: Session) -> None:
    project = _make_project(db_session)
    db_session.add(EstimateRevision(project_id=project.id, revision_number=1, is_final=False))
    db_session.add(EstimateRevision(project_id=project.id, revision_number=2, is_final=False))
    db_session.commit()

    assert db_session.query(EstimateRevision).count() == 2


def test_estimate_revision_final_flag_allowed_on_different_projects(db_session: Session) -> None:
    project_a = _make_project(db_session)
    project_b = _make_project(db_session)
    db_session.add(EstimateRevision(project_id=project_a.id, revision_number=1, is_final=True))
    db_session.add(EstimateRevision(project_id=project_b.id, revision_number=1, is_final=True))
    db_session.commit()

    assert db_session.query(EstimateRevision).count() == 2


def test_estimated_cost_can_belong_to_an_estimate_revision(db_session: Session) -> None:
    project = _make_project(db_session)
    category = _make_cost_category(db_session, "Materials")
    revision = EstimateRevision(project_id=project.id, revision_number=1)
    db_session.add(revision)
    db_session.flush()

    estimated = EstimatedCost(
        project_id=project.id,
        estimate_revision_id=revision.id,
        cost_category_id=category.id,
        amount=Decimal("780000"),
    )
    db_session.add(estimated)
    db_session.commit()

    assert estimated.estimate_revision_id == revision.id


def test_estimated_cost_without_revision_still_works(db_session: Session) -> None:
    """Backward compatibility: estimate_revision_id is optional, so existing
    (or simple) EstimatedCost rows that don't participate in revision
    history remain valid."""
    project = _make_project(db_session)
    category = _make_cost_category(db_session, "Labour")
    estimated = EstimatedCost(project_id=project.id, cost_category_id=category.id, amount=Decimal("1000"))
    db_session.add(estimated)
    db_session.commit()

    assert estimated.estimate_revision_id is None
