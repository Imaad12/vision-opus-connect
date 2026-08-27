"""Pydantic schemas for the management/reporting layer. These wrap plain
dataclasses from `app.services.management_service`/`dashboard_service`,
not ORM models -- `from_attributes=True` reads them the same way."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.core.enums import Currency, ProjectStatus


class DashboardSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_projects: int
    active_projects: int
    completed_projects: int
    total_awarded_contract_value: Decimal
    total_invoiced_revenue: Decimal
    total_actual_cost: Decimal
    total_actual_profit: Decimal
    average_actual_margin: Decimal | None
    total_estimated_profit: Decimal
    average_estimated_margin: Decimal | None


class ProjectProfitabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class VendorSpendRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vendor_id: int
    vendor_name: str
    po_committed_total: Decimal
    invoiced_total: Decimal
    paid_total: Decimal
    payable_outstanding: Decimal


class CashFlowSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cash_in: Decimal
    cash_out: Decimal
    net_cash_flow: Decimal


class OperatingIncomeSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_actual_profit: Decimal
    total_payroll_paid: Decimal
    operating_income: Decimal
