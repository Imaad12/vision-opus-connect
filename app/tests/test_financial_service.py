"""Integration tests for `app.services.financial_service`, exercised against
a real (in-memory) SQLite database.

These cover the scenarios from the Phase 2 brief that require aggregating
multiple database rows — TEST 13 (multiple invoices with different VAT/
retention) and TEST 14 (multiple actual cost entries across categories) —
plus full end-to-end snapshot construction across the whole project
lifecycle (multiple quotation revisions, approved/pending/rejected
variations, invoices, payments, retention release).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import (
    Currency,
    InvoiceDirection,
    ProjectStatus,
    QuotationStatus,
    VariationStatus,
    VendorType,
)
from app.models import (
    ActualCost,
    Client,
    Company,
    CostCategory,
    EstimatedCost,
    Invoice,
    Payment,
    Project,
    ProjectVariation,
    Quotation,
    QuotationVersion,
    Vendor,
)
from app.services.financial_service import (
    build_estimate_accuracy_report,
    build_project_financial_snapshot,
    create_estimate_revision,
    get_final_estimate_revision,
    get_latest_estimate_revision,
    get_original_estimate_revision,
    sum_estimate_revision_cost,
)


def _make_project(session: Session, name: str = "Villa Renovation") -> Project:
    company = Company(name="Vision Contracting LLC")
    client = Client(name="Acme Developers")
    session.add_all([company, client])
    session.flush()
    project = Project(company_id=company.id, client_id=client.id, name=name)
    session.add(project)
    session.flush()
    return project


def _make_category(session: Session, name: str) -> CostCategory:
    category = CostCategory(name=name)
    session.add(category)
    session.flush()
    return category


def _award_project(
    session: Session, project: Project, quoted_value: Decimal, contract_value: Decimal
) -> QuotationVersion:
    quotation = Quotation(project_id=project.id, reference_number=f"Q-{project.id}")
    session.add(quotation)
    session.flush()
    version = QuotationVersion(
        quotation_id=quotation.id,
        version_number=1,
        status=QuotationStatus.WON,
        quoted_value=quoted_value,
    )
    session.add(version)
    session.flush()
    project.contract_value = contract_value
    project.winning_quotation_version_id = version.id
    project.status = ProjectStatus.AWARDED
    session.flush()
    return version


def test_never_awarded_quotation_has_no_actual_figures(db_session: Session) -> None:
    project = _make_project(db_session)
    quotation = Quotation(project_id=project.id, reference_number="Q-LOST")
    db_session.add(quotation)
    db_session.flush()
    version = QuotationVersion(
        quotation_id=quotation.id,
        version_number=1,
        status=QuotationStatus.LOST,
        quoted_value=Decimal("500000"),
    )
    db_session.add(version)
    category = _make_category(db_session, "Materials")
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            quotation_version_id=version.id,
            cost_category_id=category.id,
            amount=Decimal("400000"),
        )
    )
    project.status = ProjectStatus.LOST
    db_session.commit()

    snapshot = build_project_financial_snapshot(db_session, project)

    assert snapshot.quoted_value == Decimal("500000")
    assert snapshot.estimated_cost == Decimal("400000")
    assert snapshot.quoted_profit == Decimal("100000")
    # Never awarded -> no revenue, no actual profit, regardless of the estimate.
    assert snapshot.awarded_contract_value is None
    assert snapshot.actual_revenue is None
    assert snapshot.actual_profit is None
    assert snapshot.project_status == ProjectStatus.LOST


def test_empty_project_has_unknown_costs_but_zero_transactional_sums(db_session: Session) -> None:
    project = _make_project(db_session)
    db_session.commit()

    snapshot = build_project_financial_snapshot(db_session, project)

    assert snapshot.quoted_value is None
    assert snapshot.estimated_cost is None
    assert snapshot.actual_cost is None
    assert snapshot.awarded_contract_value is None
    # No invoices/payments recorded is a known fact: a true zero.
    assert snapshot.invoiced_revenue == Decimal("0")
    assert snapshot.invoiced_revenue_gross == Decimal("0")
    assert snapshot.cash_received == Decimal("0")
    assert snapshot.retention_outstanding == Decimal("0")
    assert snapshot.receivables_outstanding == Decimal("0")


def test_pending_variation_excluded_from_revised_contract_value(db_session: Session) -> None:
    project = _make_project(db_session)
    _award_project(db_session, project, Decimal("1000000"), Decimal("1000000"))

    db_session.add_all(
        [
            ProjectVariation(
                project_id=project.id,
                approved_value_change=Decimal("100000"),
                status=VariationStatus.APPROVED,
            ),
            ProjectVariation(
                project_id=project.id,
                proposed_value_change=Decimal("50000"),
                status=VariationStatus.PENDING_APPROVAL,
            ),
            ProjectVariation(
                project_id=project.id,
                approved_value_change=Decimal("-25000"),
                status=VariationStatus.APPROVED,
            ),
            ProjectVariation(
                project_id=project.id,
                proposed_value_change=Decimal("10000"),
                status=VariationStatus.REJECTED,
            ),
        ]
    )
    db_session.commit()

    snapshot = build_project_financial_snapshot(db_session, project)

    # Only the two APPROVED variations count: +100,000 - 25,000 = 75,000.
    assert snapshot.approved_variation_value == Decimal("75000")
    assert snapshot.revised_contract_value == Decimal("1075000")


def test_scenario_13_multiple_invoices_different_vat_and_retention(db_session: Session) -> None:
    project = _make_project(db_session)
    _award_project(db_session, project, Decimal("1000000"), Decimal("1000000"))
    client = Client(name="Second billing contact")
    db_session.add(client)
    db_session.flush()

    invoice_1 = Invoice(
        project_id=project.id,
        direction=InvoiceDirection.CLIENT,
        client_id=project.client_id,
        amount=Decimal("210000"),
        tax_amount=Decimal("10000"),
        retention_amount=Decimal("20000"),
    )
    invoice_2 = Invoice(
        project_id=project.id,
        direction=InvoiceDirection.CLIENT,
        client_id=project.client_id,
        amount=Decimal("105000"),
        tax_amount=Decimal("5000"),
        retention_amount=Decimal("0"),
    )
    db_session.add_all([invoice_1, invoice_2])
    db_session.commit()

    snapshot = build_project_financial_snapshot(db_session, project)

    # Gross: 210,000 + 105,000 = 315,000. Net of VAT: 200,000 + 100,000 = 300,000.
    assert snapshot.invoiced_revenue_gross == Decimal("315000")
    assert snapshot.invoiced_revenue == Decimal("300000")
    # Retention withheld: 20,000 + 0 = 20,000; nothing released yet.
    assert snapshot.retention_outstanding == Decimal("20000")
    # Amount due after retention: (210,000-20,000) + (105,000-0) = 295,000;
    # nothing paid yet -> fully outstanding.
    assert snapshot.receivables_outstanding == Decimal("295000")
    assert snapshot.cash_received == Decimal("0")


def test_scenario_14_multiple_actual_costs_across_categories(db_session: Session) -> None:
    project = _make_project(db_session)
    materials = _make_category(db_session, "Materials")
    labour = _make_category(db_session, "Labour")
    subcontractors = _make_category(db_session, "Subcontractors")

    db_session.add_all(
        [
            ActualCost(
                project_id=project.id,
                cost_category_id=materials.id,
                amount=Decimal("210000"),
                tax_amount=Decimal("10000"),
                incurred_date=date(2026, 1, 15),
            ),
            ActualCost(
                project_id=project.id,
                cost_category_id=labour.id,
                amount=Decimal("150000"),
                incurred_date=date(2026, 2, 1),
            ),
            ActualCost(
                project_id=project.id,
                cost_category_id=subcontractors.id,
                amount=Decimal("105000"),
                tax_amount=Decimal("5000"),
                is_tax_recoverable=False,
                incurred_date=date(2026, 2, 15),
            ),
        ]
    )
    db_session.commit()

    snapshot = build_project_financial_snapshot(db_session, project)

    # Materials: 210,000 - 10,000 VAT (recoverable) = 200,000
    # Labour: 150,000 (no tax)
    # Subcontractors: 105,000 (non-recoverable tax -> full gross counted)
    assert snapshot.actual_cost == Decimal("200000") + Decimal("150000") + Decimal("105000")
    assert snapshot.actual_cost == Decimal("455000")


def test_retention_release_reduces_outstanding_retention(db_session: Session) -> None:
    project = _make_project(db_session)
    _award_project(db_session, project, Decimal("500000"), Decimal("500000"))

    invoice = Invoice(
        project_id=project.id,
        direction=InvoiceDirection.CLIENT,
        client_id=project.client_id,
        amount=Decimal("500000"),
        retention_amount=Decimal("25000"),
    )
    db_session.add(invoice)
    db_session.flush()

    progress_payment = Payment(
        invoice_id=invoice.id, amount=Decimal("475000"), paid_date=date(2026, 3, 1)
    )
    db_session.add(progress_payment)
    db_session.commit()

    mid_snapshot = build_project_financial_snapshot(db_session, project)
    assert mid_snapshot.retention_outstanding == Decimal("25000")
    assert mid_snapshot.cash_received == Decimal("475000")
    assert mid_snapshot.receivables_outstanding == Decimal("0")  # 475,000 due, 475,000 paid

    retention_release = Payment(
        invoice_id=invoice.id,
        amount=Decimal("25000"),
        paid_date=date(2026, 9, 1),
        is_retention_release=True,
    )
    db_session.add(retention_release)
    db_session.commit()

    final_snapshot = build_project_financial_snapshot(db_session, project)
    assert final_snapshot.retention_outstanding == Decimal("0")
    assert final_snapshot.cash_received == Decimal("500000")


def test_estimated_cost_scoped_to_winning_quotation_version_not_superseded_ones(
    db_session: Session,
) -> None:
    project = _make_project(db_session)
    materials = _make_category(db_session, "Materials")
    quotation = Quotation(project_id=project.id, reference_number="Q-MULTI")
    db_session.add(quotation)
    db_session.flush()

    v1 = QuotationVersion(
        quotation_id=quotation.id,
        version_number=1,
        status=QuotationStatus.REVISED,
        quoted_value=Decimal("900000"),
    )
    v2 = QuotationVersion(
        quotation_id=quotation.id,
        version_number=2,
        status=QuotationStatus.WON,
        quoted_value=Decimal("1000000"),
    )
    db_session.add_all([v1, v2])
    db_session.flush()

    db_session.add(
        EstimatedCost(
            project_id=project.id,
            quotation_version_id=v1.id,
            cost_category_id=materials.id,
            amount=Decimal("999999"),  # belongs to the superseded v1, must be excluded
        )
    )
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            quotation_version_id=v2.id,
            cost_category_id=materials.id,
            amount=Decimal("780000"),
        )
    )

    project.contract_value = Decimal("1000000")
    project.winning_quotation_version_id = v2.id
    project.status = ProjectStatus.AWARDED
    db_session.commit()

    snapshot = build_project_financial_snapshot(db_session, project)

    assert snapshot.quoted_value == Decimal("1000000")
    assert snapshot.estimated_cost == Decimal("780000")


def test_full_lifecycle_end_to_end_snapshot(db_session: Session) -> None:
    project = _make_project(db_session, name="Full Lifecycle Project")
    materials = _make_category(db_session, "Materials")
    labour = _make_category(db_session, "Labour")
    vendor = Vendor(vendor_type=VendorType.SUBCONTRACTOR, name="ElecSub LLC")
    db_session.add(vendor)
    db_session.flush()

    version = _award_project(db_session, project, Decimal("1000000"), Decimal("1000000"))

    db_session.add(
        EstimatedCost(
            project_id=project.id,
            quotation_version_id=version.id,
            cost_category_id=materials.id,
            amount=Decimal("500000"),
        )
    )
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            quotation_version_id=version.id,
            cost_category_id=labour.id,
            amount=Decimal("280000"),
        )
    )

    db_session.add_all(
        [
            ProjectVariation(
                project_id=project.id,
                approved_value_change=Decimal("100000"),
                status=VariationStatus.APPROVED,
            ),
            ProjectVariation(
                project_id=project.id,
                proposed_value_change=Decimal("30000"),
                status=VariationStatus.PENDING_APPROVAL,
            ),
            ProjectVariation(
                project_id=project.id,
                approved_value_change=Decimal("-25000"),
                status=VariationStatus.APPROVED,
            ),
        ]
    )

    invoice = Invoice(
        project_id=project.id,
        direction=InvoiceDirection.CLIENT,
        client_id=project.client_id,
        amount=Decimal("1050000"),
        tax_amount=Decimal("50000"),
        retention_amount=Decimal("52500"),
    )
    db_session.add(invoice)
    db_session.flush()
    db_session.add(
        Payment(invoice_id=invoice.id, amount=Decimal("700000"), paid_date=date(2026, 5, 1))
    )

    db_session.add(
        ActualCost(
            project_id=project.id,
            cost_category_id=materials.id,
            vendor_id=vendor.id,
            amount=Decimal("525000"),
            tax_amount=Decimal("25000"),
            incurred_date=date(2026, 4, 1),
        )
    )
    db_session.add(
        ActualCost(
            project_id=project.id,
            cost_category_id=labour.id,
            amount=Decimal("300000"),
            incurred_date=date(2026, 4, 15),
        )
    )
    db_session.commit()

    snapshot = build_project_financial_snapshot(db_session, project)

    assert snapshot.currency == Currency.AED
    assert snapshot.project_status == ProjectStatus.AWARDED
    assert snapshot.quoted_value == Decimal("1000000")
    assert snapshot.estimated_cost == Decimal("780000")
    assert snapshot.quoted_profit == Decimal("220000")
    assert snapshot.quoted_margin == Decimal("22.00")

    assert snapshot.awarded_contract_value == Decimal("1000000")
    assert snapshot.estimated_profit == Decimal("220000")
    assert snapshot.estimated_margin == Decimal("22.00")

    assert snapshot.approved_variation_value == Decimal("75000")
    assert snapshot.revised_contract_value == Decimal("1075000")
    assert snapshot.actual_revenue == Decimal("1075000")

    # 525,000 - 25,000 VAT (recoverable) + 300,000 = 800,000
    assert snapshot.actual_cost == Decimal("800000")
    assert snapshot.actual_profit == Decimal("275000")
    assert snapshot.actual_margin == Decimal("25.58")

    assert snapshot.cost_variance == Decimal("20000")
    assert snapshot.revenue_variance == Decimal("75000")
    assert snapshot.profit_variance == Decimal("55000")

    assert snapshot.invoiced_revenue_gross == Decimal("1050000")
    assert snapshot.invoiced_revenue == Decimal("1000000")
    assert snapshot.retention_outstanding == Decimal("52500")
    assert snapshot.cash_received == Decimal("700000")
    # Amount due after retention: 1,050,000 - 52,500 = 997,500; paid 700,000.
    assert snapshot.receivables_outstanding == Decimal("297500")


# --- Estimate revision history (original -> revised -> final) ---


def test_create_estimate_revision_auto_increments_revision_number(db_session: Session) -> None:
    project = _make_project(db_session)

    first = create_estimate_revision(db_session, project)
    second = create_estimate_revision(db_session, project)
    third = create_estimate_revision(db_session, project)
    db_session.commit()

    assert (first.revision_number, second.revision_number, third.revision_number) == (1, 2, 3)


def test_create_estimate_revision_defaults_currency_to_project_currency(db_session: Session) -> None:
    project = _make_project(db_session)
    revision = create_estimate_revision(db_session, project)
    db_session.commit()

    assert revision.currency == project.contract_currency == Currency.AED


def test_original_and_latest_revision_identification(db_session: Session) -> None:
    project = _make_project(db_session)
    category = _make_category(db_session, "Materials")

    rev1 = create_estimate_revision(db_session, project, effective_date=date(2026, 1, 1))
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=rev1.id,
            cost_category_id=category.id,
            amount=Decimal("780000"),
        )
    )
    rev2 = create_estimate_revision(db_session, project, effective_date=date(2026, 3, 1))
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=rev2.id,
            cost_category_id=category.id,
            amount=Decimal("820000"),
        )
    )
    db_session.commit()

    original = get_original_estimate_revision(db_session, project)
    latest = get_latest_estimate_revision(db_session, project)

    assert original.id == rev1.id
    assert latest.id == rev2.id
    assert sum_estimate_revision_cost(db_session, original) == Decimal("780000")
    assert sum_estimate_revision_cost(db_session, latest) == Decimal("820000")


def test_original_revision_is_never_overwritten_by_a_later_one(db_session: Session) -> None:
    """The core requirement: revising the estimate must never mutate the
    original revision's cost lines."""
    project = _make_project(db_session)
    category = _make_category(db_session, "Materials")

    rev1 = create_estimate_revision(db_session, project)
    original_line = EstimatedCost(
        project_id=project.id,
        estimate_revision_id=rev1.id,
        cost_category_id=category.id,
        amount=Decimal("780000"),
    )
    db_session.add(original_line)
    db_session.commit()

    rev2 = create_estimate_revision(db_session, project)
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=rev2.id,
            cost_category_id=category.id,
            amount=Decimal("850000"),
        )
    )
    rev3 = create_estimate_revision(db_session, project, is_final=True)
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=rev3.id,
            cost_category_id=category.id,
            amount=Decimal("820000"),
        )
    )
    db_session.commit()

    # The original row is untouched — same id, same amount — regardless of
    # how many later revisions were created.
    db_session.refresh(original_line)
    assert original_line.amount == Decimal("780000")
    assert sum_estimate_revision_cost(db_session, rev1) == Decimal("780000")
    assert sum_estimate_revision_cost(db_session, rev2) == Decimal("850000")
    assert sum_estimate_revision_cost(db_session, rev3) == Decimal("820000")


def test_final_estimate_explicit_flag_wins_over_latest(db_session: Session) -> None:
    project = _make_project(db_session)

    create_estimate_revision(db_session, project)
    explicit_final = create_estimate_revision(db_session, project, is_final=True)
    latest_but_not_final = create_estimate_revision(db_session, project)
    db_session.commit()

    final = get_final_estimate_revision(db_session, project)

    assert final.id == explicit_final.id
    assert final.id != latest_but_not_final.id


def test_final_estimate_falls_back_to_latest_before_completion_date(db_session: Session) -> None:
    project = _make_project(db_session, name="Completed Project")
    project.actual_completion_date = date(2026, 6, 1)

    create_estimate_revision(db_session, project, effective_date=date(2026, 1, 1))
    before_completion = create_estimate_revision(db_session, project, effective_date=date(2026, 5, 1))
    after_completion = create_estimate_revision(db_session, project, effective_date=date(2026, 8, 1))
    db_session.commit()

    final = get_final_estimate_revision(db_session, project)

    # The revision made AFTER completion must not be picked as "final as of completion".
    assert final.id == before_completion.id
    assert final.id != after_completion.id


def test_final_estimate_falls_back_to_latest_when_project_not_completed(db_session: Session) -> None:
    project = _make_project(db_session)
    create_estimate_revision(db_session, project)
    latest = create_estimate_revision(db_session, project)
    db_session.commit()

    final = get_final_estimate_revision(db_session, project)

    assert final.id == latest.id


def test_final_estimate_is_none_when_no_revision_precedes_completion(db_session: Session) -> None:
    project = _make_project(db_session)
    project.actual_completion_date = date(2026, 1, 1)
    # Only revision is dated after the (unusually early) completion date.
    create_estimate_revision(db_session, project, effective_date=date(2026, 6, 1))
    db_session.commit()

    assert get_final_estimate_revision(db_session, project) is None


def test_final_estimate_uses_created_at_when_effective_date_missing(db_session: Session) -> None:
    project = _make_project(db_session)
    project.actual_completion_date = date(2026, 12, 31)
    # No effective_date given -> falls back to created_at's date, which is "today".
    only_revision = create_estimate_revision(db_session, project)
    db_session.commit()

    final = get_final_estimate_revision(db_session, project)
    assert final.id == only_revision.id


def test_estimate_revision_none_when_no_revisions_recorded(db_session: Session) -> None:
    project = _make_project(db_session)
    db_session.commit()

    assert get_original_estimate_revision(db_session, project) is None
    assert get_latest_estimate_revision(db_session, project) is None
    assert get_final_estimate_revision(db_session, project) is None


def test_build_estimate_accuracy_report_full_lifecycle(db_session: Session) -> None:
    project = _make_project(db_session, name="Accuracy Report Project")
    category = _make_category(db_session, "Materials")
    project.actual_completion_date = date(2026, 12, 1)

    original = create_estimate_revision(db_session, project, effective_date=date(2026, 1, 1))
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=original.id,
            cost_category_id=category.id,
            amount=Decimal("780000"),
        )
    )
    create_estimate_revision(db_session, project, effective_date=date(2026, 6, 1))  # a mid-project revision
    final = create_estimate_revision(db_session, project, is_final=True, effective_date=date(2026, 11, 1))
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=final.id,
            cost_category_id=category.id,
            amount=Decimal("820000"),
        )
    )
    db_session.add(
        ActualCost(project_id=project.id, cost_category_id=category.id, amount=Decimal("800000"))
    )
    db_session.commit()

    report = build_estimate_accuracy_report(db_session, project)

    assert report.original_revision_number == 1
    assert report.original_estimate == Decimal("780000")
    assert report.final_revision_number == 3
    assert report.final_estimate == Decimal("820000")
    assert report.actual_cost == Decimal("800000")
    assert report.estimate_change == Decimal("40000")
    # Original underestimated by 20,000; final overestimated by 20,000.
    assert report.original_estimate_variance == Decimal("20000")
    assert report.final_estimate_variance == Decimal("-20000")


def test_build_estimate_accuracy_report_with_no_revisions_yet(db_session: Session) -> None:
    project = _make_project(db_session)
    category = _make_category(db_session, "Materials")
    db_session.add(
        ActualCost(project_id=project.id, cost_category_id=category.id, amount=Decimal("500000"))
    )
    db_session.commit()

    report = build_estimate_accuracy_report(db_session, project)

    assert report.original_estimate is None
    assert report.final_estimate is None
    assert report.actual_cost == Decimal("500000")
    assert report.estimate_change is None
    assert report.original_estimate_variance is None


def test_estimate_revision_is_independent_of_quotation_version(db_session: Session) -> None:
    """A re-estimate made during execution (post-award) has no quotation
    version to attach to at all — EstimateRevision must support that."""
    project = _make_project(db_session)
    category = _make_category(db_session, "Labour")
    _award_project(db_session, project, Decimal("1000000"), Decimal("1000000"))

    post_award_revision = create_estimate_revision(db_session, project)
    assert post_award_revision.quotation_version_id is None

    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=post_award_revision.id,
            cost_category_id=category.id,
            amount=Decimal("900000"),
        )
    )
    db_session.commit()

    assert sum_estimate_revision_cost(db_session, post_award_revision) == Decimal("900000")


def test_snapshot_estimated_cost_uses_only_latest_revision_not_all_of_them(db_session: Session) -> None:
    """Regression test: a project with multiple estimate revisions (e.g.
    revision 2 copy-forwarded from revision 1, per
    app.services.cost_service.start_new_estimate_revision) must count only
    the latest revision's lines toward the live snapshot's estimated_cost —
    counting every revision's lines would double (or triple) count
    copied-forward lines."""
    project = _make_project(db_session)
    category = _make_category(db_session, "Materials")

    revision_1 = create_estimate_revision(db_session, project)
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=revision_1.id,
            cost_category_id=category.id,
            amount=Decimal("780000"),
        )
    )
    db_session.commit()

    # Revision 2 "copies forward" the same line (a new row, same amount)
    # plus one additional line, as the real UI flow does.
    revision_2 = create_estimate_revision(db_session, project)
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=revision_2.id,
            cost_category_id=category.id,
            amount=Decimal("780000"),
        )
    )
    db_session.add(
        EstimatedCost(
            project_id=project.id,
            estimate_revision_id=revision_2.id,
            cost_category_id=category.id,
            amount=Decimal("40000"),
        )
    )
    db_session.commit()

    snapshot = build_project_financial_snapshot(db_session, project)

    # Only revision 2's total (820,000), never revision_1 + revision_2 (1,600,000).
    assert snapshot.estimated_cost == Decimal("820000")
