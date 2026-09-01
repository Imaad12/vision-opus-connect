"""End-to-end tests for the `/vendors` API routes -- same pattern as
`test_api_clients.py`, via the shared helpers in `api_test_support.py`."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.tests.api_test_support import make_api_client, make_memory_engine


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    engine = make_memory_engine()
    granted = {"suppliers.view", "suppliers.create", "suppliers.edit"}
    yield from make_api_client(engine, granted)
    engine.dispose()


def test_create_and_list_vendors(api_client: TestClient):
    response = api_client.post("/vendors", json={"name": "Al Rashid Steel Trading"})
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Al Rashid Steel Trading"
    assert created["vendor_type"] == "SUPPLIER"
    assert created["is_active"] is True

    listing = api_client.get("/vendors")
    assert listing.status_code == 200
    names = [v["name"] for v in listing.json()]
    assert "Al Rashid Steel Trading" in names


def test_create_a_subcontractor_vendor(api_client: TestClient):
    response = api_client.post(
        "/vendors", json={"name": "Falcon MEP Contracting", "vendor_type": "SUBCONTRACTOR"}
    )
    assert response.status_code == 201
    assert response.json()["vendor_type"] == "SUBCONTRACTOR"


def test_get_single_vendor(api_client: TestClient):
    created = api_client.post("/vendors", json={"name": "Beta Supplies"}).json()

    response = api_client.get(f"/vendors/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Beta Supplies"


def test_get_missing_vendor_is_404(api_client: TestClient):
    response = api_client.get("/vendors/999999")
    assert response.status_code == 404


def test_create_vendor_without_a_name_is_422(api_client: TestClient):
    response = api_client.post("/vendors", json={"name": "   "})
    assert response.status_code == 422


def test_update_vendor(api_client: TestClient):
    created = api_client.post("/vendors", json={"name": "Gamma Trading"}).json()

    response = api_client.put(
        f"/vendors/{created['id']}",
        json={"name": "Gamma Trading LLC", "tax_number": "300123456700003", "is_active": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Gamma Trading LLC"
    assert body["tax_number"] == "300123456700003"
    assert body["is_active"] is False


def test_list_vendors_without_view_permission_is_403(api_client: TestClient):
    api_client.granted.discard("suppliers.view")  # type: ignore[attr-defined]

    response = api_client.get("/vendors")

    assert response.status_code == 403


def test_create_vendor_without_create_permission_is_403(api_client: TestClient):
    api_client.granted.discard("suppliers.create")  # type: ignore[attr-defined]

    response = api_client.post("/vendors", json={"name": "Should Not Be Created"})

    assert response.status_code == 403
