"""End-to-end tests for the management/reporting layer: dashboard summary,
project profitability, vendor spend, cash flow, operating income.
"""

from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.tests.api_test_support import make_api_client, make_memory_engine


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    engine = make_memory_engine()
    granted = {
        "customers.view",
        "customers.create",
        "suppliers.view",
        "suppliers.create",
        "projects.view",
        "projects.create",
        "purchasing.po_create",
        "purchasing.po_approve",
        "finance.invoices",
        "finance.payments",
        "finance.reports",
        "employees.view",
        "employees.manage",
    }
    yield from make_api_client(engine, granted)
    engine.dispose()


@pytest.fixture
def client_id(api_client: TestClient) -> int:
    return api_client.post("/clients", json={"name": "Al Rashid Group"}).json()["id"]


@pytest.fixture
def vendor_id(api_client: TestClient) -> int:
    return api_client.post("/vendors", json={"name": "Gulf Building Materials"}).json()["id"]


@pytest.fixture
def project_id(api_client: TestClient, client_id: int) -> int:
    return api_client.post("/projects", json={"name": "Mall Fit-Out", "client_id": client_id}).json()["id"]


def test_dashboard_summary_is_open_to_any_authenticated_user(api_client: TestClient):
    response = api_client.get("/management/dashboard-summary")
    assert response.status_code == 200
    body = response.json()
    assert "total_projects" in body


def test_dashboard_summary_counts_projects(api_client: TestClient, project_id: int):
    response = api_client.get("/management/dashboard-summary")
    assert response.status_code == 200
    assert response.json()["total_projects"] >= 1


def test_project_profitability_reflects_real_invoices_and_costs(
    api_client: TestClient, project_id: int, client_id: int
):
    invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "CLIENT", "client_id": client_id, "amount": "10000.00"},
    ).json()
    api_client.post(f"/invoices/{invoice['id']}/issue")
    api_client.post(
        "/payments", json={"invoice_id": invoice["id"], "amount": "5000.00", "paid_date": "2026-01-15"}
    )

    response = api_client.get("/management/project-profitability")
    assert response.status_code == 200
    rows = response.json()
    assert any(r["project_id"] == project_id for r in rows)


def test_vendor_spend_aggregates_po_and_invoices(api_client: TestClient, project_id: int, vendor_id: int):
    po = api_client.post(
        "/purchase-orders",
        json={"po_number": "PO-001", "vendor_id": vendor_id, "project_id": project_id},
    ).json()
    api_client.put(
        f"/purchase-orders/{po['id']}/lines",
        json={"lines": [{"description": "Cement", "quantity": "10", "unit_price": "50"}]},
    )

    vendor_invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "VENDOR", "vendor_id": vendor_id, "amount": "500.00"},
    ).json()
    api_client.post(f"/invoices/{vendor_invoice['id']}/issue")
    api_client.post(
        "/payments",
        json={"invoice_id": vendor_invoice["id"], "amount": "200.00", "paid_date": "2026-01-20"},
    )

    response = api_client.get("/management/vendor-spend")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["vendor_id"] == vendor_id
    assert row["po_committed_total"] == "575.00"  # 500 subtotal + 15% VAT
    assert row["invoiced_total"] == "500.00"
    assert row["paid_total"] == "200.00"
    assert row["payable_outstanding"] == "300.00"


def test_vendor_with_no_activity_is_excluded(api_client: TestClient, vendor_id: int):
    response = api_client.get("/management/vendor-spend")
    assert response.status_code == 200
    assert response.json() == []


def test_cash_flow_separates_client_and_vendor_payments(
    api_client: TestClient, project_id: int, client_id: int, vendor_id: int
):
    client_invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "CLIENT", "client_id": client_id, "amount": "10000.00"},
    ).json()
    api_client.post(f"/invoices/{client_invoice['id']}/issue")
    api_client.post(
        "/payments", json={"invoice_id": client_invoice["id"], "amount": "4000.00", "paid_date": "2026-01-15"}
    )

    vendor_invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "VENDOR", "vendor_id": vendor_id, "amount": "1500.00"},
    ).json()
    api_client.post(f"/invoices/{vendor_invoice['id']}/issue")
    api_client.post(
        "/payments", json={"invoice_id": vendor_invoice["id"], "amount": "1000.00", "paid_date": "2026-01-20"}
    )

    response = api_client.get("/management/cash-flow")
    assert response.status_code == 200
    body = response.json()
    assert body["cash_in"] == "4000.00"
    assert body["cash_out"] == "1000.00"
    assert body["net_cash_flow"] == "3000.00"


def test_operating_income_deducts_paid_payroll(api_client: TestClient, project_id: int, client_id: int):
    invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "CLIENT", "client_id": client_id, "amount": "10000.00"},
    ).json()
    api_client.post(f"/invoices/{invoice['id']}/issue")
    api_client.post(
        "/payments", json={"invoice_id": invoice["id"], "amount": "10000.00", "paid_date": "2026-01-15"}
    )

    employee = api_client.post("/employees", json={"full_name": "John Smith"}).json()
    record = api_client.post(
        "/payroll-records",
        json={
            "employee_id": employee["id"],
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gross_amount": "3000.00",
        },
    ).json()
    api_client.post(f"/payroll-records/{record['id']}/approve")
    api_client.post(f"/payroll-records/{record['id']}/pay", json={"paid_date": "2026-02-01"})

    response = api_client.get("/management/operating-income")
    assert response.status_code == 200
    body = response.json()
    assert body["total_payroll_paid"] == "3000.00"
    assert Decimal(body["operating_income"]) == Decimal(body["total_actual_profit"]) - Decimal("3000.00")


def test_unapproved_payroll_not_counted_in_operating_income(api_client: TestClient):
    employee = api_client.post("/employees", json={"full_name": "Jane Doe"}).json()
    api_client.post(
        "/payroll-records",
        json={
            "employee_id": employee["id"],
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gross_amount": "3000.00",
        },
    )

    response = api_client.get("/management/operating-income")
    assert response.status_code == 200
    assert response.json()["total_payroll_paid"] == "0"


def test_finance_reports_permission_required_for_project_profitability():
    engine = make_memory_engine()
    client_gen = make_api_client(engine, set())
    client = next(client_gen)
    response = client.get("/management/project-profitability")
    assert response.status_code == 403
    engine.dispose()
