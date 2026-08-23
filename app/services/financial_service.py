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

from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import InvoiceDirection, InvoiceStatus, VariationStatus
from app.core.financial_engine import (
    ProjectFinancialSnapshot,
    calculate_amount_due_after_retention,
    calculate_net_of_tax,
    calculate_outstanding_balance,
    calculate_recognized_cost,
)
from app.models import (
    ActualCost,
    EstimatedCost,
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
    the most recently created version across all of the project's
    quotations (covering a project still at tender stage, possibly with
    multiple revisions)."""
    if project.winning_quotation_version_id is not None:
        return session.get(QuotationVersion, project.winning_quotation_version_id)

    stmt = (
        select(QuotationVersion)
        .join(Quotation, QuotationVersion.quotation_id == Quotation.id)
        .where(Quotation.project_id == project.id, QuotationVersion.is_deleted.is_(False))
        .order_by(QuotationVersion.id.desc())
    )
    return session.execute(stmt).scalars().first()


def _estimated_cost_condition(quotation_version: QuotationVersion | None):
    """EstimatedCost rows that belong to the relevant quotation version, plus
    project-level rows not tied to any specific version. Rows tied to a
    *different* (superseded) quotation version are excluded so an old,
    lost revision's estimate is never double-counted against the current
    one."""
    if quotation_version is not None:
        return (EstimatedCost.quotation_version_id == quotation_version.id) | (
            EstimatedCost.quotation_version_id.is_(None)
        )
    return EstimatedCost.quotation_version_id.is_(None)


def build_project_financial_snapshot(session: Session, project: Project) -> ProjectFinancialSnapshot:
    """Aggregate a project's financial rows into a ProjectFinancialSnapshot.

    All arithmetic happens in `app.core.financial_engine`; this function's
    job is only to query and sum rows into the Decimal inputs it needs.
    """
    quotation_version = _get_relevant_quotation_version(session, project)
    quoted_value = quotation_version.quoted_value if quotation_version else None

    estimated_cost_rows = (
        session.execute(
            select(EstimatedCost.amount).where(
                EstimatedCost.project_id == project.id,
                EstimatedCost.is_deleted.is_(False),
                _estimated_cost_condition(quotation_version),
            )
        )
        .scalars()
        .all()
    )
    estimated_cost = _sum_or_none(list(estimated_cost_rows))

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
    actual_cost = _sum_or_none([cost for cost in recognized_costs if cost is not None])

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
