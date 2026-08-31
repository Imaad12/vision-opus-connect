"""Database-backed financial aggregation.

This is the only module that both reads financial rows from the database
AND feeds them into `app.core.financial_engine` — the arithmetic itself
stays in that pure, DB-free module; this module's job is limited to
querying and summing rows into the Decimal inputs the engine needs. This
keeps financial calculations independent from the UI and separates
database access from financial business logic, per the project's
architecture rules.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Currency, InvoiceDirection, InvoiceStatus, VariationStatus
from app.core.financial_engine import (
    EstimateAccuracyReport,
    ProjectFinancialSnapshot,
    calculate_actual_profit,
    calculate_amount_due_after_retention,
    calculate_net_of_tax,
    calculate_outstanding_balance,
    calculate_recognized_cost,
    calculate_revised_contract_value,
)
from app.models import (
    ActualCost,
    EstimatedCost,
    EstimateRevision,
    Invoice,
    Payment,
    Project,
    ProjectVariation,
    Quotation,
    QuotationVersion,
)

ZERO: Final[Decimal] = Decimal("0")


def _sum_or_none(values: list[Decimal]) -> Decimal | None:
    """Sum a list of Decimals, or None if the list is empty.

    Used for judgment-based figures (estimated cost, actual cost) where
    "no rows recorded yet" usually means "not entered yet", not
    "genuinely zero" — see FINANCIAL_MODEL.md. Contrast with transactional
    sums (invoices, payments), which use a true zero for an empty list
    since "no invoices raised yet" is itself a known fact.
    """
    if not values:
        return None
    return sum(values, ZERO)


def _get_relevant_quotation_version(session: Session, project: Project) -> QuotationVersion | None:
    """The quotation version representing this project's current quoted
    basis: the winning version if the project has been awarded, otherwise
    the chronologically most recent version (by `issued_date`, not by
    insertion order) across all of the project's quotations (covering a
    project still at tender stage, possibly with multiple revisions).

    Ordering by `issued_date` rather than `id`/insertion order matters
    once revisions can be confirmed out of order (e.g. two scanned
    documents for the same quotation reviewed in whichever order they
    happened to be processed) — "current" must mean "dated most recently,"
    never "entered into the system most recently." See
    `app.services.quotation_service.get_current_version` (the equivalent,
    single-quotation version of this ordering) and
    `app.services.import_service.confirm_import`'s revision-conflict
    handling, which is what keeps an out-of-order revision from reaching
    this table without an explicit reviewer decision in the first place.
    """
    if project.winning_quotation_version_id is not None:
        return session.get(QuotationVersion, project.winning_quotation_version_id)

    stmt = (
        select(QuotationVersion)
        .join(Quotation, QuotationVersion.quotation_id == Quotation.id)
        .where(Quotation.project_id == project.id, QuotationVersion.is_deleted.is_(False))
        .order_by(QuotationVersion.issued_date.desc().nulls_last(), QuotationVersion.id.desc())
    )
    return session.execute(stmt).scalars().first()


def _estimated_cost_condition(
    quotation_version: QuotationVersion | None, latest_revision: EstimateRevision | None
):
    """Which EstimatedCost rows count toward the project's current
    estimated cost.

    If the project has any `EstimateRevision` history (created via
    `app.services.cost_service`), the current estimate is unambiguous:
    exactly the latest revision's lines — never anything from an older
    revision, since `start_new_estimate_revision` copies lines forward, so
    counting both the old and new revision would double-count every copied
    line.

    Otherwise (no revision history exists for this project — e.g. legacy
    data, or a project whose only cost lines were entered directly against
    a quotation version), fall back to the original Phase 2 scoping: rows
    tied to the relevant quotation version, plus version-independent rows
    not tied to any revision either.
    """
    if latest_revision is not None:
        return EstimatedCost.estimate_revision_id == latest_revision.id

    no_revision = EstimatedCost.estimate_revision_id.is_(None)
    if quotation_version is not None:
        return (EstimatedCost.quotation_version_id == quotation_version.id) | (
            EstimatedCost.quotation_version_id.is_(None) & no_revision
        )
    return EstimatedCost.quotation_version_id.is_(None) & no_revision


def _sum_actual_cost(session: Session, project: Project) -> Decimal | None:
    """Sum the recognized (tax-adjusted) amount of every ActualCost row for
    a project. Shared by `build_project_financial_snapshot` and
    `build_estimate_accuracy_report` so the two never compute "actual cost"
    two different ways."""
    actual_cost_rows = session.execute(
        select(ActualCost.amount, ActualCost.tax_amount, ActualCost.is_tax_recoverable).where(
            ActualCost.project_id == project.id,
            ActualCost.is_deleted.is_(False),
        )
    ).all()
    recognized_costs = [
        calculate_recognized_cost(amount, tax_amount, is_tax_recoverable)
        for amount, tax_amount, is_tax_recoverable in actual_cost_rows
    ]
    return _sum_or_none([cost for cost in recognized_costs if cost is not None])


def build_project_financial_snapshot(session: Session, project: Project) -> ProjectFinancialSnapshot:
    """Aggregate a project's financial rows into a ProjectFinancialSnapshot.

    All arithmetic happens in `app.core.financial_engine`; this function's
    job is only to query and sum rows into the Decimal inputs it needs.
    """
    quotation_version = _get_relevant_quotation_version(session, project)
    quoted_value = quotation_version.quoted_value if quotation_version else None
    latest_revision = get_latest_estimate_revision(session, project)

    estimated_cost_rows = (
        session.execute(
            select(EstimatedCost.amount).where(
                EstimatedCost.project_id == project.id,
                EstimatedCost.is_deleted.is_(False),
                _estimated_cost_condition(quotation_version, latest_revision),
            )
        )
        .scalars()
        .all()
    )
    estimated_cost = _sum_or_none(list(estimated_cost_rows))

    actual_cost = _sum_actual_cost(session, project)

    approved_variation_rows = (
        session.execute(
            select(ProjectVariation.approved_value_change).where(
                ProjectVariation.project_id == project.id,
                ProjectVariation.is_deleted.is_(False),
                ProjectVariation.status == VariationStatus.APPROVED,
                ProjectVariation.approved_value_change.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    approved_variation_value = sum(approved_variation_rows, ZERO)

    client_invoices = (
        session.execute(
            select(Invoice).where(
                Invoice.project_id == project.id,
                Invoice.direction == InvoiceDirection.CLIENT,
                Invoice.is_deleted.is_(False),
                Invoice.status != InvoiceStatus.CANCELLED,
            )
        )
        .scalars()
        .all()
    )

    invoiced_revenue_gross = sum((invoice.amount for invoice in client_invoices), ZERO)
    invoiced_revenue = sum(
        (calculate_net_of_tax(invoice.amount, invoice.tax_amount) or ZERO for invoice in client_invoices),
        ZERO,
    )
    amount_due_after_retention_total = sum(
        (
            calculate_amount_due_after_retention(invoice.amount, invoice.retention_amount) or ZERO
            for invoice in client_invoices
        ),
        ZERO,
    )
    retention_withheld_total = sum((invoice.retention_amount or ZERO for invoice in client_invoices), ZERO)

    invoice_ids = [invoice.id for invoice in client_invoices]
    payments = (
        session.execute(
            select(Payment).where(Payment.invoice_id.in_(invoice_ids), Payment.is_deleted.is_(False))
        )
        .scalars()
        .all()
        if invoice_ids
        else []
    )

    cash_received = sum((payment.amount for payment in payments), ZERO)
    retention_released_total = sum(
        (payment.amount for payment in payments if payment.is_retention_release), ZERO
    )
    retention_outstanding = retention_withheld_total - retention_released_total
    receivables_outstanding = (
        calculate_outstanding_balance(amount_due_after_retention_total, cash_received) or ZERO
    )

    return ProjectFinancialSnapshot(
        currency=project.contract_currency,
        project_status=project.status,
        quoted_value=quoted_value,
        estimated_cost=estimated_cost,
        awarded_contract_value=project.contract_value,
        approved_variation_value=approved_variation_value,
        actual_cost=actual_cost,
        invoiced_revenue=invoiced_revenue,
        invoiced_revenue_gross=invoiced_revenue_gross,
        retention_outstanding=retention_outstanding,
        receivables_outstanding=receivables_outstanding,
        cash_received=cash_received,
    )


def compute_total_actual_profit(session: Session) -> Decimal:
    """Portfolio-wide `sum(actual_profit)` across every non-deleted
    project -- the one figure `management_service.compute_operating_income`
    actually needs.

    `build_project_financial_snapshot` above computes this correctly, but
    at the cost of ~7 queries scoped to one project each; calling it once
    per project in a loop (`project_service.list_projects_with_snapshots`)
    measured as the dominant cost of `GET /management/operating-income`
    (linear in project count -- 57ms at 10 projects, 452ms at 100, against
    real Postgres, while every other Dashboard-relevant endpoint stayed
    flat regardless of project count).

    `actual_profit = actual_revenue - actual_cost`, where `actual_revenue
    = awarded_contract_value + approved_variation_value` (see
    `app.core.financial_engine`). Neither term depends on quoted_value,
    estimated_cost, estimate revisions, invoices, or payments -- so unlike
    the full snapshot, this figure alone can be computed from exactly 3
    queries covering *every* project, not one query per project. Every
    number here still goes through the same `app.core.financial_engine`
    functions `build_project_financial_snapshot` uses (`safe_subtract`,
    `calculate_revised_contract_value`, `calculate_recognized_cost`,
    `calculate_actual_profit`) -- this only changes how the rows feeding
    them are fetched, not the arithmetic itself."""
    projects = session.execute(
        select(Project.id, Project.contract_value).where(Project.is_deleted.is_(False))
    ).all()

    variation_rows = session.execute(
        select(ProjectVariation.project_id, ProjectVariation.approved_value_change).where(
            ProjectVariation.is_deleted.is_(False),
            ProjectVariation.status == VariationStatus.APPROVED,
            ProjectVariation.approved_value_change.is_not(None),
        )
    ).all()
    variations_by_project: dict[int, Decimal] = {}
    for project_id, approved_value_change in variation_rows:
        variations_by_project[project_id] = (
            variations_by_project.get(project_id, ZERO) + approved_value_change
        )

    cost_rows = session.execute(
        select(ActualCost.project_id, ActualCost.amount, ActualCost.tax_amount, ActualCost.is_tax_recoverable).where(
            ActualCost.is_deleted.is_(False)
        )
    ).all()
    recognized_costs_by_project: dict[int, list[Decimal]] = {}
    for project_id, amount, tax_amount, is_tax_recoverable in cost_rows:
        recognized = calculate_recognized_cost(amount, tax_amount, is_tax_recoverable)
        if recognized is not None:
            recognized_costs_by_project.setdefault(project_id, []).append(recognized)

    total_actual_profit = ZERO
    for project_id, contract_value in projects:
        actual_revenue = calculate_revised_contract_value(
            contract_value, variations_by_project.get(project_id)
        )
        actual_cost = _sum_or_none(recognized_costs_by_project.get(project_id, []))
        actual_profit = calculate_actual_profit(actual_revenue, actual_cost)
        total_actual_profit += actual_profit or ZERO

    return total_actual_profit


# --- Estimate revision history (for multi-year estimating-accuracy analysis) ---


def list_estimate_revisions(session: Session, project: Project) -> list[EstimateRevision]:
    """All of a project's estimate revisions, oldest first, never including
    soft-deleted ones."""
    stmt = (
        select(EstimateRevision)
        .where(EstimateRevision.project_id == project.id, EstimateRevision.is_deleted.is_(False))
        .order_by(EstimateRevision.revision_number)
    )
    return list(session.execute(stmt).scalars().all())


def create_estimate_revision(
    session: Session,
    project: Project,
    *,
    effective_date: date | None = None,
    is_final: bool = False,
    quotation_version_id: int | None = None,
    currency: Currency | None = None,
    notes: str | None = None,
) -> EstimateRevision:
    """Start a new estimate revision for a project, auto-assigning the next
    sequential `revision_number`. This is the only supported way to add a
    new estimate snapshot: existing revisions and their `EstimatedCost`
    rows are never touched, so estimating history is preserved by
    construction rather than by convention.
    """
    existing = list_estimate_revisions(session, project)
    next_revision_number = existing[-1].revision_number + 1 if existing else 1

    revision = EstimateRevision(
        project_id=project.id,
        quotation_version_id=quotation_version_id,
        revision_number=next_revision_number,
        effective_date=effective_date,
        is_final=is_final,
        currency=currency or project.contract_currency,
        notes=notes,
    )
    session.add(revision)
    session.flush()
    return revision


def get_original_estimate_revision(session: Session, project: Project) -> EstimateRevision | None:
    """The first estimate ever recorded for this project (lowest revision_number)."""
    revisions = list_estimate_revisions(session, project)
    return revisions[0] if revisions else None


def get_latest_estimate_revision(session: Session, project: Project) -> EstimateRevision | None:
    """The most recently created estimate revision, regardless of project status."""
    revisions = list_estimate_revisions(session, project)
    return revisions[-1] if revisions else None


def get_final_estimate_revision(session: Session, project: Project) -> EstimateRevision | None:
    """The revision that should be treated as this project's closing estimate.

    Preference order:
    1. The revision explicitly flagged `is_final=True` (at most one can
       exist per project — enforced by a DB constraint).
    2. If the project has an `actual_completion_date`, the latest revision
       effective at or before that date. If no revision qualifies (e.g. all
       revisions happen to be dated after completion — unusual, but
       possible with backdated data entry), returns None rather than
       guessing.
    3. Otherwise (project not yet completed and nothing flagged final), the
       latest revision overall — the "latest" and "final" figures are the
       same thing until the project actually finishes.
    """
    revisions = list_estimate_revisions(session, project)
    if not revisions:
        return None

    explicit_final = next((revision for revision in revisions if revision.is_final), None)
    if explicit_final is not None:
        return explicit_final

    if project.actual_completion_date is not None:
        eligible = [
            revision
            for revision in revisions
            if (revision.effective_date or revision.created_at.date()) <= project.actual_completion_date
        ]
        return max(eligible, key=lambda revision: revision.revision_number) if eligible else None

    return revisions[-1]


def sum_estimate_revision_cost(session: Session, revision: EstimateRevision) -> Decimal | None:
    """Sum the EstimatedCost rows belonging to one specific estimate revision."""
    rows = (
        session.execute(
            select(EstimatedCost.amount).where(
                EstimatedCost.estimate_revision_id == revision.id,
                EstimatedCost.is_deleted.is_(False),
            )
        )
        .scalars()
        .all()
    )
    return _sum_or_none(list(rows))


def build_estimate_accuracy_report(session: Session, project: Project) -> EstimateAccuracyReport:
    """Compare a project's original and final cost estimates against its
    actual cost, answering: what did we originally estimate, what was our
    closing estimate, how much did the estimate move, and how accurate was
    each one.
    """
    original_revision = get_original_estimate_revision(session, project)
    final_revision = get_final_estimate_revision(session, project)

    return EstimateAccuracyReport(
        currency=project.contract_currency,
        original_revision_number=original_revision.revision_number if original_revision else None,
        original_estimate=sum_estimate_revision_cost(session, original_revision)
        if original_revision
        else None,
        final_revision_number=final_revision.revision_number if final_revision else None,
        final_estimate=sum_estimate_revision_cost(session, final_revision) if final_revision else None,
        actual_cost=_sum_actual_cost(session, project),
    )
