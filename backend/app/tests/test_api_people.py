"""End-to-end tests for the People domain: Employee, PayrollRecord."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.tests.api_test_support import make_api_client, make_memory_engine


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    engine = make_memory_engine()
    granted = {"employees.view", "employees.manage"}
    yield from make_api_client(engine, granted)
    engine.dispose()


@pytest.fixture
def employee_id(api_client: TestClient) -> int:
    return api_client.post(
        "/employees", json={"full_name": "John Smith", "position": "Site Engineer"}
    ).json()["id"]


# ---------------------------------------------------------------- Employees


def test_create_and_list_employee(api_client: TestClient):
    response = api_client.post("/employees", json={"full_name": "John Smith", "position": "Site Engineer"})
    assert response.status_code == 201
    created = response.json()
    assert created["employment_status"] == "ACTIVE"

    listing = api_client.get("/employees")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_create_employee_without_name_is_422(api_client: TestClient):
    response = api_client.post("/employees", json={"full_name": "  "})
    assert response.status_code == 422


def test_employee_termination_before_hire_is_422(api_client: TestClient):
    response = api_client.post(
        "/employees",
        json={"full_name": "Jane Doe", "hire_date": "2026-06-01", "termination_date": "2026-01-01"},
    )
    assert response.status_code == 422


def test_update_employee(api_client: TestClient, employee_id: int):
    updated = api_client.put(
        f"/employees/{employee_id}",
        json={"full_name": "John Smith", "employment_status": "ON_LEAVE"},
    )
    assert updated.status_code == 200
    assert updated.json()["employment_status"] == "ON_LEAVE"


def test_employee_not_found_is_404(api_client: TestClient):
    response = api_client.get("/employees/999")
    assert response.status_code == 404


# ---------------------------------------------------------------- Payroll


def test_create_payroll_record_computes_net_amount(api_client: TestClient, employee_id: int):
    response = api_client.post(
        "/payroll-records",
        json={
            "employee_id": employee_id,
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "gross_amount": "5000.00",
            "deductions": "200.00",
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["net_amount"] == "4800.00"
    assert created["status"] == "DRAFT"


def test_payroll_period_end_before_start_is_422(api_client: TestClient, employee_id: int):
    response = api_client.post(
        "/payroll-records",
        json={
            "employee_id": employee_id,
            "period_start": "2026-08-31",
            "period_end": "2026-08-01",
            "gross_amount": "5000.00",
        },
    )
    assert response.status_code == 422


def test_payroll_deductions_cannot_exceed_gross(api_client: TestClient, employee_id: int):
    response = api_client.post(
        "/payroll-records",
        json={
            "employee_id": employee_id,
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "gross_amount": "1000.00",
            "deductions": "2000.00",
        },
    )
    assert response.status_code == 422


def test_approve_then_pay_payroll_record(api_client: TestClient, employee_id: int):
    record = api_client.post(
        "/payroll-records",
        json={
            "employee_id": employee_id,
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "gross_amount": "5000.00",
        },
    ).json()

    approved = api_client.post(f"/payroll-records/{record['id']}/approve")
    assert approved.json()["status"] == "APPROVED"

    paid = api_client.post(f"/payroll-records/{record['id']}/pay", json={"paid_date": "2026-09-01"})
    assert paid.status_code == 200
    assert paid.json()["status"] == "PAID"
    assert paid.json()["paid_date"] == "2026-09-01"


def test_cannot_pay_a_draft_payroll_record(api_client: TestClient, employee_id: int):
    record = api_client.post(
        "/payroll-records",
        json={
            "employee_id": employee_id,
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "gross_amount": "5000.00",
        },
    ).json()

    paid = api_client.post(f"/payroll-records/{record['id']}/pay", json={"paid_date": "2026-09-01"})
    assert paid.status_code == 422


def test_payroll_record_not_found_is_404(api_client: TestClient):
    response = api_client.get("/payroll-records/999")
    assert response.status_code == 404
