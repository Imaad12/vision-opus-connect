"""End-to-end tests for the Finance domain: Invoice, Payment, Expense
(ActualCost). Same pattern as `test_api_procurement.py` via
`api_test_support.py`.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.models import CostCategory
from app.tests.api_test_support import make_api_client, make_memory_engine


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    e = make_memory_engine()
    yield e
    e.dispose()


@pytest.fixture
def api_client(engine: Engine) -> Generator[TestClient, None, None]:
    granted = {
        "customers.view",
        "customers.create",
        "suppliers.view",
        "suppliers.create",
        "projects.view",
        "projects.create",
        "finance.invoices",
        "finance.payments",
        "finance.expenses",
    }
    yield from make_api_client(engine, granted)


@pytest.fixture
def project_id(api_client: TestClient) -> int:
    client = api_client.post("/clients", json={"name": "Al Otaibi Retail"}).json()
    project = api_client.post(
        "/projects", json={"name": "Mall Fit-Out", "client_id": client["id"]}
    ).json()
    return project["id"]


@pytest.fixture
def client_id(api_client: TestClient) -> int:
    return api_client.post("/clients", json={"name": "Al Rashid Group"}).json()["id"]


@pytest.fixture
def vendor_id(api_client: TestClient) -> int:
    return api_client.post("/vendors", json={"name": "Gulf Building Materials"}).json()["id"]


@pytest.fixture
def cost_category_id(engine: Engine) -> int:
    factory = sessionmaker(bind=engine, future=True)
    with factory() as session:
        category = CostCategory(name="Materials")
        session.add(category)
        session.commit()
        return category.id


# ---------------------------------------------------------------- Invoices


def test_create_and_list_client_invoice(api_client: TestClient, project_id: int, client_id: int):
    response = api_client.post(
        "/invoices",
        json={
            "project_id": project_id,
            "direction": "CLIENT",
            "client_id": client_id,
            "amount": "10000.00",
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "DRAFT"
    assert created["amount_paid"] == "0.00"

    listing = api_client.get("/invoices", params={"project_id": project_id})
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_client_invoice_requires_client_not_vendor(api_client: TestClient, project_id: int, vendor_id: int):
    response = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "CLIENT", "vendor_id": vendor_id, "amount": "5000.00"},
    )
    assert response.status_code == 422


def test_vendor_invoice_requires_vendor_not_client(api_client: TestClient, project_id: int, client_id: int):
    response = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "VENDOR", "client_id": client_id, "amount": "5000.00"},
    )
    assert response.status_code == 422


def test_issue_then_full_payment_marks_invoice_paid(api_client: TestClient, project_id: int, client_id: int):
    invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "CLIENT", "client_id": client_id, "amount": "10000.00"},
    ).json()

    issued = api_client.post(f"/invoices/{invoice['id']}/issue")
    assert issued.json()["status"] == "ISSUED"

    payment = api_client.post(
        "/payments",
        json={"invoice_id": invoice["id"], "amount": "10000.00", "paid_date": "2026-01-15"},
    )
    assert payment.status_code == 201

    refreshed = api_client.get(f"/invoices/{invoice['id']}").json()
    assert refreshed["status"] == "PAID"
    assert refreshed["amount_paid"] == "10000.00"


def test_partial_payment_sets_partially_paid(api_client: TestClient, project_id: int, client_id: int):
    invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "CLIENT", "client_id": client_id, "amount": "10000.00"},
    ).json()
    api_client.post(f"/invoices/{invoice['id']}/issue")

    api_client.post(
        "/payments",
        json={"invoice_id": invoice["id"], "amount": "4000.00", "paid_date": "2026-01-15"},
    )

    refreshed = api_client.get(f"/invoices/{invoice['id']}").json()
    assert refreshed["status"] == "PARTIALLY_PAID"
    assert refreshed["amount_paid"] == "4000.00"


def test_retention_is_excluded_from_amount_due(api_client: TestClient, project_id: int, client_id: int):
    invoice = api_client.post(
        "/invoices",
        json={
            "project_id": project_id,
            "direction": "CLIENT",
            "client_id": client_id,
            "amount": "10000.00",
            "retention_amount": "1000.00",
        },
    ).json()
    api_client.post(f"/invoices/{invoice['id']}/issue")

    payment = api_client.post(
        "/payments",
        json={"invoice_id": invoice["id"], "amount": "9000.00", "paid_date": "2026-01-15"},
    )
    assert payment.status_code == 201

    refreshed = api_client.get(f"/invoices/{invoice['id']}").json()
    assert refreshed["status"] == "PAID"


def test_cannot_pay_a_draft_invoice(api_client: TestClient, project_id: int, client_id: int):
    invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "CLIENT", "client_id": client_id, "amount": "10000.00"},
    ).json()

    payment = api_client.post(
        "/payments",
        json={"invoice_id": invoice["id"], "amount": "1000.00", "paid_date": "2026-01-15"},
    )
    assert payment.status_code == 422


def test_cannot_cancel_invoice_with_payments(api_client: TestClient, project_id: int, client_id: int):
    invoice = api_client.post(
        "/invoices",
        json={"project_id": project_id, "direction": "CLIENT", "client_id": client_id, "amount": "10000.00"},
    ).json()
    api_client.post(f"/invoices/{invoice['id']}/issue")
    api_client.post(
        "/payments",
        json={"invoice_id": invoice["id"], "amount": "1000.00", "paid_date": "2026-01-15"},
    )

    cancelled = api_client.post(f"/invoices/{invoice['id']}/cancel")
    assert cancelled.status_code == 422


def test_invoice_not_found_is_404(api_client: TestClient):
    response = api_client.get("/invoices/999")
    assert response.status_code == 404


# ---------------------------------------------------------------- Expenses


def test_create_and_list_expense(api_client: TestClient, project_id: int, cost_category_id: int, vendor_id: int):
    response = api_client.post(
        "/expenses",
        json={
            "project_id": project_id,
            "cost_category_id": cost_category_id,
            "vendor_id": vendor_id,
            "amount": "1500.00",
            "tax_amount": "225.00",
            "description": "Cement delivery",
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["amount"] == "1500.00"

    listing = api_client.get("/expenses", params={"project_id": project_id})
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_update_expense(api_client: TestClient, project_id: int, cost_category_id: int):
    expense = api_client.post(
        "/expenses",
        json={"project_id": project_id, "cost_category_id": cost_category_id, "amount": "1000.00"},
    ).json()

    updated = api_client.put(
        f"/expenses/{expense['id']}",
        json={
            "project_id": project_id,
            "cost_category_id": cost_category_id,
            "amount": "1200.00",
            "description": "Revised amount",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["amount"] == "1200.00"
    assert updated.json()["description"] == "Revised amount"


def test_expense_tax_amount_cannot_exceed_gross_amount(api_client: TestClient, project_id: int, cost_category_id: int):
    response = api_client.post(
        "/expenses",
        json={
            "project_id": project_id,
            "cost_category_id": cost_category_id,
            "amount": "100.00",
            "tax_amount": "200.00",
        },
    )
    assert response.status_code == 422


def test_expense_not_found_is_404(api_client: TestClient):
    response = api_client.get("/expenses/999")
    assert response.status_code == 404


def test_list_cost_categories(api_client: TestClient, cost_category_id: int):
    response = api_client.get("/cost-categories")
    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert "Materials" in names
