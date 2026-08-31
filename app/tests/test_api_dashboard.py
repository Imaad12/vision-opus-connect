"""`GET /dashboard/summary` -- correctness of the aggregated KPI numbers
and per-card permission gating. See `app/api/routers/dashboard.py` for
why this endpoint exists (replacing 5 full-list fetches the Dashboard
page used to make just to compute these same numbers client-side).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.tests.api_test_support import make_api_client, make_memory_engine

FULL_PERMISSIONS = {
    "customers.view",
    "customers.create",
    "suppliers.view",
    "suppliers.create",
    "projects.view",
    "projects.create",
    "projects.edit",
    "leads.view",
    "leads.create",
    "quotations.view",
    "purchasing.po_create",
    "purchasing.po_approve",
    "finance.invoices",
    "finance.payments",
}


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    engine = make_memory_engine()
    yield from make_api_client(engine, set(FULL_PERMISSIONS))
    engine.dispose()


@pytest.fixture
def seeded(api_client: TestClient) -> dict:
    client_id = api_client.post("/clients", json={"name": "Acme Client"}).json()["id"]
    vendor_id = api_client.post("/vendors", json={"name": "Acme Vendor"}).json()["id"]

    # Leads: one open (counts toward pipeline), one WON (excluded).
    api_client.post(
        "/leads", json={"title": "Open lead", "estimated_value": "1000.00", "status": "NEW"}
    )
    api_client.post(
        "/leads", json={"title": "Won lead", "estimated_value": "5000.00", "status": "WON"}
    )

    # Projects: one active (IN_PROGRESS), one terminal (COMPLETED).
    # `contract_value` is only ever set by `quotation_service.mark_awarded`
    # (see projects.py's router docstring), never by direct edit -- so
    # this test only exercises the count/status side of the KPI, not the
    # value side (that would need a full quotation-award flow, out of
    # scope for this endpoint's own test).
    active_project = api_client.post(
        "/projects", json={"name": "Active Project", "client_id": client_id}
    ).json()
    api_client.put(
        f"/projects/{active_project['id']}",
        json={"name": "Active Project", "client_id": client_id, "status": "IN_PROGRESS"},
    )
    done_project = api_client.post(
        "/projects", json={"name": "Done Project", "client_id": client_id}
    ).json()
    api_client.put(
        f"/projects/{done_project['id']}",
        json={"name": "Done Project", "client_id": client_id, "status": "COMPLETED"},
    )

    # Purchase order pending approval.
    po = api_client.post(
        "/purchase-orders",
        json={"po_number": "PO-1", "vendor_id": vendor_id, "project_id": active_project["id"]},
    ).json()
    api_client.put(
        f"/purchase-orders/{po['id']}/lines",
        json={"lines": [{"line_no": 1, "description": "Item", "quantity": "1", "unit_price": "100.00"}]},
    )
    api_client.post(f"/purchase-orders/{po['id']}/submit")

    # Client invoice, partially paid -- receivables = amount - amount_paid.
    invoice = api_client.post(
        "/invoices",
        json={
            "project_id": active_project["id"], "direction": "CLIENT", "client_id": client_id,
            "amount": "1000.00", "tax_amount": "50.00",
        },
    ).json()
    api_client.post(f"/invoices/{invoice['id']}/issue")
    api_client.post(
        "/payments", json={"invoice_id": invoice["id"], "amount": "300.00", "paid_date": "2026-01-15"}
    )

    return {"client_id": client_id, "vendor_id": vendor_id, "active_project": active_project}


def test_dashboard_summary_matches_expected_kpis(api_client: TestClient, seeded: dict):
    response = api_client.get("/dashboard/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["pipeline_value"] == "1000.00"
    assert data["awaiting_count"] == 0
    assert data["active_projects_count"] == 1
    assert data["active_projects_value"] == "0.00"
    assert data["receivables"] == "700.00"
    assert data["po_pending_count"] == 1


def test_dashboard_summary_omits_sections_without_permission(api_client: TestClient, seeded: dict):
    api_client.granted.discard("leads.view")
    api_client.granted.discard("projects.view")

    response = api_client.get("/dashboard/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["pipeline_value"] is None
    assert data["active_projects_count"] is None
    assert data["active_projects_value"] is None
    # Untouched permissions still compute.
    assert data["po_pending_count"] == 1
    assert data["receivables"] == "700.00"


def test_dashboard_summary_all_null_without_any_relevant_permission(api_client: TestClient):
    api_client.granted.clear()
    api_client.granted.add("customers.view")  # unrelated to any dashboard card

    response = api_client.get("/dashboard/summary")
    assert response.status_code == 200
    data = response.json()

    assert all(value is None for value in data.values())
