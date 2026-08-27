"""Management-layer aggregation: project profitability ranking, vendor
spend, portfolio cash flow, and operating income.

Same rule as `dashboard_service.py`: no profit/margin/cash formula is
reimplemented here. This module only queries rows and combines figures
`app.core.financial_engine` and `financial_service`/`dashboard_service`
already compute correctly, at a wider (multi-project / multi-vendor)
scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (
    Currency,
    InvoiceDirection,
    InvoiceStatus,
    PayrollStatus,
    ProjectStatus,
    PurchaseOrderStatus,
)
from app.core.financial_engine import (
    calculate_amount_due_after_retention,
    calculate_net_of_tax,
    calculate_outstanding_balance,
)
from app.models import Invoice, Payment, PayrollRecord, PurchaseOrder, Vendor
from app.services.dashboard_service import build_dashboard_summary
from app.services.project_service import list_projects_with_snapshots

ZERO: Final[Decimal] = Decimal("0")


@dataclass(frozen=True)
class ProjectProfitability:
    project_id: int
    project_name: str
    client_name: str | None
    status: ProjectStatus
    currency: Currency
    contract_value: Decimal | None
    actual_cost: Decimal | None
    actual_profit: Decimal | None
    actual_margin: Decimal | None
    receivables_outstanding: Decimal


def compute_project_profitability(session: Session) -> list[ProjectProfitability]:
    """Every non-deleted project's real (actual, not quoted/estimated)
    profitability, most profitable first. A project with no revenue yet
    (`actual_profit is None`) sorts last, not first -- `None` is "not yet
    measurable", not "worst", but it still can't rank above a real number.
    """
    pairs = list_projects_with_snapshots(session)
    rows = [
        ProjectProfitability(
            project_id=project.id,
            project_name=project.name,
            client_name=project.client.name if project.client else None,
            status=project.status,
            currency=snapshot.currency,
            contract_value=snapshot.awarded_contract_value,
            actual_cost=snapshot.actual_cost,
            actual_profit=snapshot.actual_profit,
            actual_margin=snapshot.actual_margin,
            receivables_outstanding=snapshot.receivables_outstanding,
        )
        for project, snapshot in pairs
    ]
    return sorted(
        rows,
        key=lambda r: (r.actual_profit is None, -(r.actual_profit or ZERO)),
    )


@dataclass(frozen=True)
class VendorSpend:
    vendor_id: int
    vendor_name: str
    po_committed_total: Decimal
    invoiced_total: Decimal
    paid_total: Decimal
    payable_outstanding: Decimal


def compute_vendor_spend(session: Session) -> list[VendorSpend]:
    """Per-vendor spend, largest invoiced total first. Mirrors exactly the
    client-side invoice/payment/retention math `financial_service.
    build_project_financial_snapshot` already does per project, just
    grouped by vendor (AP) instead of by project (AR)."""
    vendors = list(
        session.execute(select(Vendor).where(Vendor.is_deleted.is_(False))).scalars().all()
    )

    po_totals: dict[int, Decimal] = {}
    for vendor_id, total in session.execute(
        select(PurchaseOrder.vendor_id, PurchaseOrder.total).where(
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
        )
    ).all():
        po_totals[vendor_id] = po_totals.get(vendor_id, ZERO) + total

    rows: list[VendorSpend] = []
    for vendor in vendors:
        vendor_invoices = list(
            session.execute(
                select(Invoice).where(
                    Invoice.vendor_id == vendor.id,
                    Invoice.direction == InvoiceDirection.VENDOR,
                    Invoice.is_deleted.is_(False),
                    Invoice.status != InvoiceStatus.CANCELLED,
                )
            )
            .scalars()
            .all()
        )
        invoiced_total = sum(
            (calculate_net_of_tax(inv.amount, inv.tax_amount) or ZERO for inv in vendor_invoices), ZERO
        )
        amount_due_total = sum(
            (
                calculate_amount_due_after_retention(inv.amount, inv.retention_amount) or ZERO
                for inv in vendor_invoices
            ),
            ZERO,
        )
        invoice_ids = [inv.id for inv in vendor_invoices]
        paid_total = ZERO
        if invoice_ids:
            paid_total = sum(
                (
                    session.execute(
                        select(Payment.amount).where(
                            Payment.invoice_id.in_(invoice_ids), Payment.is_deleted.is_(False)
                        )
                    )
                    .scalars()
                    .all()
                ),
                ZERO,
            )

        po_total = po_totals.get(vendor.id, ZERO)
        if po_total == ZERO and invoiced_total == ZERO:
            continue

        rows.append(
            VendorSpend(
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                po_committed_total=po_total,
                invoiced_total=invoiced_total,
                paid_total=paid_total,
                payable_outstanding=calculate_outstanding_balance(amount_due_total, paid_total) or ZERO,
            )
        )

    return sorted(rows, key=lambda r: r.invoiced_total, reverse=True)


@dataclass(frozen=True)
class CashFlowSummary:
    cash_in: Decimal
    cash_out: Decimal
    net_cash_flow: Decimal


def compute_cash_flow_summary(session: Session) -> CashFlowSummary:
    """Portfolio-wide cash actually collected from clients vs. actually
    paid to vendors -- both from recorded `Payment` rows (never from
    invoice face values, which are receivables/payables, not cash)."""
    cash_in = sum(
        (
            session.execute(
                select(Payment.amount)
                .join(Invoice, Payment.invoice_id == Invoice.id)
                .where(Payment.is_deleted.is_(False), Invoice.direction == InvoiceDirection.CLIENT)
            )
            .scalars()
            .all()
        ),
        ZERO,
    )
    cash_out = sum(
        (
            session.execute(
                select(Payment.amount)
                .join(Invoice, Payment.invoice_id == Invoice.id)
                .where(Payment.is_deleted.is_(False), Invoice.direction == InvoiceDirection.VENDOR)
            )
            .scalars()
            .all()
        ),
        ZERO,
    )
    return CashFlowSummary(cash_in=cash_in, cash_out=cash_out, net_cash_flow=cash_in - cash_out)


@dataclass(frozen=True)
class OperatingIncomeSummary:
    total_actual_profit: Decimal
    total_payroll_paid: Decimal
    operating_income: Decimal


def compute_operating_income(session: Session) -> OperatingIncomeSummary:
    """A deliberately narrow definition: total project-level actual profit
    minus total paid payroll. There is no general company-overhead/G&A
    expense concept in this system yet (every `ActualCost` row requires a
    `project_id`) -- this is the honest, currently-computable operating
    income, not a placeholder for a fuller P&L that would need a new
    expense category this milestone doesn't introduce."""
    total_actual_profit = build_dashboard_summary(session).total_actual_profit
    total_payroll_paid = sum(
        (
            session.execute(
                select(PayrollRecord.net_amount).where(
                    PayrollRecord.is_deleted.is_(False), PayrollRecord.status == PayrollStatus.PAID
                )
            )
            .scalars()
            .all()
        ),
        ZERO,
    )
    return OperatingIncomeSummary(
        total_actual_profit=total_actual_profit,
        total_payroll_paid=total_payroll_paid,
        operating_income=total_actual_profit - total_payroll_paid,
    )
