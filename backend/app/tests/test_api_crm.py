"""End-to-end tests for the CRM domain: Contact, Lead."""

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
        "projects.view",
        "projects.create",
        "contacts.view",
        "contacts.create",
        "contacts.edit",
        "leads.view",
        "leads.create",
        "leads.edit",
    }
    yield from make_api_client(engine, granted)
    engine.dispose()


@pytest.fixture
def client_id(api_client: TestClient) -> int:
    return api_client.post("/clients", json={"name": "Al Rashid Group"}).json()["id"]


# ---------------------------------------------------------------- Contacts


def test_create_and_list_contact(api_client: TestClient, client_id: int):
    response = api_client.post(
        "/contacts",
        json={"client_id": client_id, "full_name": "Jane Doe", "job_title": "Procurement Manager"},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["full_name"] == "Jane Doe"

    listing = api_client.get("/contacts", params={"client_id": client_id})
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_create_contact_without_name_is_422(api_client: TestClient, client_id: int):
    response = api_client.post("/contacts", json={"client_id": client_id, "full_name": "  "})
    assert response.status_code == 422


def test_create_contact_with_invalid_client_is_422(api_client: TestClient):
    response = api_client.post("/contacts", json={"client_id": 999, "full_name": "Jane Doe"})
    assert response.status_code == 422


def test_update_contact(api_client: TestClient, client_id: int):
    contact = api_client.post("/contacts", json={"client_id": client_id, "full_name": "Jane Doe"}).json()
    updated = api_client.put(
        f"/contacts/{contact['id']}",
        json={"client_id": client_id, "full_name": "Jane Smith", "is_primary": True},
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Jane Smith"
    assert updated.json()["is_primary"] is True


def test_contact_not_found_is_404(api_client: TestClient):
    response = api_client.get("/contacts/999")
    assert response.status_code == 404


# ---------------------------------------------------------------- Leads


def test_create_and_list_lead(api_client: TestClient, client_id: int):
    response = api_client.post(
        "/leads",
        json={
            "title": "New Villa Fit-Out",
            "client_id": client_id,
            "source": "REFERRAL",
            "estimated_value": "500000.00",
            "probability": 40,
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "NEW"

    listing = api_client.get("/leads")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_create_lead_without_title_is_422(api_client: TestClient):
    response = api_client.post("/leads", json={"title": "  "})
    assert response.status_code == 422


def test_lead_probability_out_of_range_is_422(api_client: TestClient):
    response = api_client.post("/leads", json={"title": "Opportunity", "probability": 150})
    assert response.status_code == 422


def test_lead_does_not_require_a_client(api_client: TestClient):
    response = api_client.post("/leads", json={"title": "Cold enquiry"})
    assert response.status_code == 201


def test_update_lead_to_won_with_converted_project(api_client: TestClient, client_id: int):
    project = api_client.post(
        "/projects", json={"name": "New Villa", "client_id": client_id}
    ).json()
    lead = api_client.post("/leads", json={"title": "New Villa Fit-Out", "client_id": client_id}).json()

    updated = api_client.put(
        f"/leads/{lead['id']}",
        json={
            "title": "New Villa Fit-Out",
            "client_id": client_id,
            "status": "WON",
            "converted_project_id": project["id"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "WON"
    assert updated.json()["converted_project_id"] == project["id"]


def test_lead_not_found_is_404(api_client: TestClient):
    response = api_client.get("/leads/999")
    assert response.status_code == 404
