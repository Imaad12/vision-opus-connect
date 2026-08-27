"""End-to-end tests for the procurement domain: Purchase Requests,
Supplier Purchase Orders (the real ERP concept -- not the renamed
ClientAwardEvidence), and Receipts. Same pattern as `test_api_clients.py`
via `api_test_support.py`.
"""

from __future__ import annotations

from collections.abc import Generator

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
        "purchasing.request",
        "purchasing.po_create",
        "purchasing.po_approve",
        "purchasing.receive",
    }
    yield from make_api_client(engine, granted)
    engine.dispose()


@pytest.fixture
def project_id(api_client: TestClient) -> int:
    client = api_client.post("/clients", json={"name": "Al Otaibi Retail"}).json()
    project = api_client.post(
        "/projects", json={"name": "Mall Fit-Out", "client_id": client["id"]}
    ).json()
    return project["id"]


@pytest.fixture
def vendor_id(api_client: TestClient) -> int:
    vendor = api_client.post("/vendors", json={"name": "Gulf Building Materials"}).json()
    return vendor["id"]


# ---------------------------------------------------------------- Purchase Requests


def test_create_and_list_purchase_request(api_client: TestClient, project_id: int):
    response = api_client.post(
        "/purchase-requests",
        json={"project_id": project_id, "items_description": "50 bags of cement"},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "DRAFT"
    assert created["project"]["id"] == project_id

    listing = api_client.get("/purchase-requests", params={"project_id": project_id})
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_create_purchase_request_without_description_is_422(api_client: TestClient, project_id: int):
    response = api_client.post("/purchase-requests", json={"project_id": project_id, "items_description": "  "})
    assert response.status_code == 422


def test_submit_and_approve_purchase_request(api_client: TestClient, project_id: int):
    pr = api_client.post(
        "/purchase-requests", json={"project_id": project_id, "items_description": "Rebar"}
    ).json()

    submitted = api_client.post(f"/purchase-requests/{pr['id']}/submit")
    assert submitted.json()["status"] == "SUBMITTED"

    approved = api_client.post(f"/purchase-requests/{pr['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"


def test_cannot_approve_a_draft_purchase_request(api_client: TestClient, project_id: int):
    pr = api_client.post(
        "/purchase-requests", json={"project_id": project_id, "items_description": "Rebar"}
    ).json()

    response = api_client.post(f"/purchase-requests/{pr['id']}/approve")

    assert response.status_code == 422


def test_get_missing_purchase_request_is_404(api_client: TestClient):
    response = api_client.get("/purchase-requests/999999")
    assert response.status_code == 404


# ---------------------------------------------------------------- Purchase Orders


def test_create_purchase_order_and_list_it(api_client: TestClient, project_id: int, vendor_id: int):
    response = api_client.post(
        "/purchase-orders",
        json={"po_number": "PO-2026-001", "vendor_id": vendor_id, "project_id": project_id},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "DRAFT"
    assert created["subtotal"] == "0.00"
    assert created["vendor"]["id"] == vendor_id
    assert created["project"]["id"] == project_id

    listing = api_client.get("/purchase-orders", params={"project_id": project_id})
    assert listing.status_code == 200
    numbers = [po["po_number"] for po in listing.json()]
    assert "PO-2026-001" in numbers


def test_duplicate_po_number_is_422(api_client: TestClient, project_id: int, vendor_id: int):
    api_client.post(
        "/purchase-orders", json={"po_number": "PO-DUP", "vendor_id": vendor_id, "project_id": project_id}
    )

    response = api_client.post(
        "/purchase-orders", json={"po_number": "PO-DUP", "vendor_id": vendor_id, "project_id": project_id}
    )

    assert response.status_code == 422


def test_set_lines_computes_totals(api_client: TestClient, project_id: int, vendor_id: int):
    po = api_client.post(
        "/purchase-orders",
        json={"po_number": "PO-LINES", "vendor_id": vendor_id, "project_id": project_id, "vat_rate": "15.00"},
    ).json()

    response = api_client.put(
        f"/purchase-orders/{po['id']}/lines",
        json={
            "lines": [
                {"description": "Cement bags", "unit": "bag", "quantity": "100", "unit_price": "20.00"},
                {"description": "Rebar 12mm", "unit": "ton", "quantity": "2", "unit_price": "3000.00"},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subtotal"] == "8000.00"
    assert body["vat_amount"] == "1200.00"
    assert body["total"] == "9200.00"
    assert len(body["lines"]) == 2
    assert body["lines"][0]["line_total"] == "2000.00"


def test_submit_requires_at_least_one_line(api_client: TestClient, project_id: int, vendor_id: int):
    po = api_client.post(
        "/purchase-orders", json={"po_number": "PO-EMPTY", "vendor_id": vendor_id, "project_id": project_id}
    ).json()

    response = api_client.post(f"/purchase-orders/{po['id']}/submit")

    assert response.status_code == 422


def test_full_po_approval_lifecycle(api_client: TestClient, project_id: int, vendor_id: int):
    po = api_client.post(
        "/purchase-orders", json={"po_number": "PO-FULL", "vendor_id": vendor_id, "project_id": project_id}
    ).json()
    api_client.put(
        f"/purchase-orders/{po['id']}/lines",
        json={"lines": [{"description": "Tiles", "unit": "m2", "quantity": "10", "unit_price": "50.00"}]},
    )

    submitted = api_client.post(f"/purchase-orders/{po['id']}/submit")
    assert submitted.json()["status"] == "PENDING_APPROVAL"

    approved = api_client.post(f"/purchase-orders/{po['id']}/approve")
    assert approved.json()["status"] == "APPROVED"


def test_cannot_edit_lines_once_submitted(api_client: TestClient, project_id: int, vendor_id: int):
    po = api_client.post(
        "/purchase-orders", json={"po_number": "PO-LOCKED", "vendor_id": vendor_id, "project_id": project_id}
    ).json()
    api_client.put(
        f"/purchase-orders/{po['id']}/lines",
        json={"lines": [{"description": "Paint", "unit": "can", "quantity": "5", "unit_price": "40.00"}]},
    )
    api_client.post(f"/purchase-orders/{po['id']}/submit")

    response = api_client.put(
        f"/purchase-orders/{po['id']}/lines",
        json={"lines": [{"description": "More paint", "unit": "can", "quantity": "1", "unit_price": "40.00"}]},
    )

    assert response.status_code == 422


def test_cancel_purchase_order(api_client: TestClient, project_id: int, vendor_id: int):
    po = api_client.post(
        "/purchase-orders", json={"po_number": "PO-CANCEL", "vendor_id": vendor_id, "project_id": project_id}
    ).json()

    response = api_client.post(f"/purchase-orders/{po['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_get_missing_purchase_order_is_404(api_client: TestClient):
    response = api_client.get("/purchase-orders/999999")
    assert response.status_code == 404


def test_list_purchase_orders_without_permission_is_403(api_client: TestClient):
    api_client.granted.discard("purchasing.po_create")  # type: ignore[attr-defined]

    response = api_client.get("/purchase-orders")

    assert response.status_code == 403


# ---------------------------------------------------------------- Receipts


@pytest.fixture
def approved_po(api_client: TestClient, project_id: int, vendor_id: int) -> dict:
    po = api_client.post(
        "/purchase-orders", json={"po_number": "PO-RECEIVE", "vendor_id": vendor_id, "project_id": project_id}
    ).json()
    po = api_client.put(
        f"/purchase-orders/{po['id']}/lines",
        json={
            "lines": [
                {"description": "Steel beams", "unit": "pc", "quantity": "10", "unit_price": "500.00"},
            ]
        },
    ).json()
    api_client.post(f"/purchase-orders/{po['id']}/submit")
    approved = api_client.post(f"/purchase-orders/{po['id']}/approve").json()
    return approved


def test_receiving_cannot_happen_before_approval(api_client: TestClient, project_id: int, vendor_id: int):
    po = api_client.post(
        "/purchase-orders", json={"po_number": "PO-NOTYET", "vendor_id": vendor_id, "project_id": project_id}
    ).json()

    response = api_client.post(
        f"/purchase-orders/{po['id']}/receipts",
        json={"receipt_date": "2026-02-01", "lines": [{"purchase_order_line_id": 1, "quantity_received": "1"}]},
    )

    assert response.status_code == 422


def test_partial_then_full_receipt_updates_po_status(api_client: TestClient, approved_po: dict):
    line_id = approved_po["lines"][0]["id"]

    partial = api_client.post(
        f"/purchase-orders/{approved_po['id']}/receipts",
        json={"receipt_date": "2026-02-01", "lines": [{"purchase_order_line_id": line_id, "quantity_received": "4"}]},
    )
    assert partial.status_code == 201

    po_after_partial = api_client.get(f"/purchase-orders/{approved_po['id']}").json()
    assert po_after_partial["status"] == "PARTIALLY_RECEIVED"
    assert po_after_partial["lines"][0]["received_quantity"] == "4.000"

    full = api_client.post(
        f"/purchase-orders/{approved_po['id']}/receipts",
        json={"receipt_date": "2026-02-05", "lines": [{"purchase_order_line_id": line_id, "quantity_received": "6"}]},
    )
    assert full.status_code == 201

    po_after_full = api_client.get(f"/purchase-orders/{approved_po['id']}").json()
    assert po_after_full["status"] == "RECEIVED"


def test_cannot_over_receive(api_client: TestClient, approved_po: dict):
    line_id = approved_po["lines"][0]["id"]

    response = api_client.post(
        f"/purchase-orders/{approved_po['id']}/receipts",
        json={"receipt_date": "2026-02-01", "lines": [{"purchase_order_line_id": line_id, "quantity_received": "999"}]},
    )

    assert response.status_code == 422


def test_cancel_receipt_reverses_received_quantity(api_client: TestClient, approved_po: dict):
    line_id = approved_po["lines"][0]["id"]
    receipt = api_client.post(
        f"/purchase-orders/{approved_po['id']}/receipts",
        json={"receipt_date": "2026-02-01", "lines": [{"purchase_order_line_id": line_id, "quantity_received": "10"}]},
    ).json()

    cancelled = api_client.post(f"/receipts/{receipt['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    po_after = api_client.get(f"/purchase-orders/{approved_po['id']}").json()
    assert po_after["status"] == "APPROVED"
    assert po_after["lines"][0]["received_quantity"] == "0.000"


def test_list_receipts_for_a_purchase_order(api_client: TestClient, approved_po: dict):
    line_id = approved_po["lines"][0]["id"]
    api_client.post(
        f"/purchase-orders/{approved_po['id']}/receipts",
        json={"receipt_date": "2026-02-01", "lines": [{"purchase_order_line_id": line_id, "quantity_received": "1"}]},
    )

    response = api_client.get(f"/purchase-orders/{approved_po['id']}/receipts")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_missing_receipt_is_404(api_client: TestClient):
    response = api_client.get("/receipts/999999")
    assert response.status_code == 404
