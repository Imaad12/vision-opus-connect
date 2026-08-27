"""End-to-end tests for the `/contracts` API routes -- same pattern as
`test_api_clients.py`, via the shared helpers in `api_test_support.py`.

A contract can only be created for an awarded project, so these tests
build the full customer -> project -> quotation -> award chain through
the real API first, exactly as a real caller would.
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
        "projects.view",
        "projects.create",
        "quotations.view",
        "quotations.create",
        "quotations.approve",
        "contracts.view",
        "contracts.create",
        "contracts.edit",
    }
    yield from make_api_client(engine, granted)
    engine.dispose()


@pytest.fixture
def awarded_project_id(api_client: TestClient) -> int:
    client = api_client.post("/clients", json={"name": "Al Zamil Group"}).json()
    project = api_client.post(
        "/projects", json={"name": "Logistics Hub", "client_id": client["id"]}
    ).json()
    version = api_client.post(
        f"/projects/{project['id']}/quotations", json={"title": "Logistics hub proposal"}
    ).json()
    award = api_client.post(
        f"/quotation-versions/{version['id']}/award", json={"contract_value": "500000.00"}
    )
    assert award.status_code == 200
    return project["id"]


@pytest.fixture
def unawarded_project_id(api_client: TestClient) -> int:
    client = api_client.post("/clients", json={"name": "Bin Dasmal Trading"}).json()
    project = api_client.post(
        "/projects", json={"name": "Not Yet Awarded", "client_id": client["id"]}
    ).json()
    return project["id"]


def test_create_contract_for_an_awarded_project(api_client: TestClient, awarded_project_id: int):
    response = api_client.post(
        f"/projects/{awarded_project_id}/contracts",
        json={"contract_number": "CTR-2026-001", "signed_date": "2026-01-15"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == awarded_project_id
    assert body["contract_number"] == "CTR-2026-001"
    assert body["value"] == "500000.00"
    assert body["status"] == "DRAFT"


def test_create_contract_for_an_unawarded_project_is_422(api_client: TestClient, unawarded_project_id: int):
    response = api_client.post(f"/projects/{unawarded_project_id}/contracts", json={})

    assert response.status_code == 422


def test_create_contract_for_missing_project_is_404(api_client: TestClient):
    response = api_client.post("/projects/999999/contracts", json={})

    assert response.status_code == 404


def test_a_project_cannot_have_two_contracts(api_client: TestClient, awarded_project_id: int):
    first = api_client.post(f"/projects/{awarded_project_id}/contracts", json={})
    assert first.status_code == 201

    second = api_client.post(f"/projects/{awarded_project_id}/contracts", json={})

    assert second.status_code == 422


def test_get_contract_for_project_and_by_id(api_client: TestClient, awarded_project_id: int):
    created = api_client.post(f"/projects/{awarded_project_id}/contracts", json={}).json()

    by_project = api_client.get(f"/projects/{awarded_project_id}/contract")
    assert by_project.status_code == 200
    assert by_project.json()["id"] == created["id"]

    by_id = api_client.get(f"/contracts/{created['id']}")
    assert by_id.status_code == 200
    assert by_id.json()["id"] == created["id"]


def test_get_contract_for_a_project_without_one_is_404(api_client: TestClient, unawarded_project_id: int):
    response = api_client.get(f"/projects/{unawarded_project_id}/contract")
    assert response.status_code == 404


def test_get_missing_contract_is_404(api_client: TestClient):
    response = api_client.get("/contracts/999999")
    assert response.status_code == 404


def test_activate_then_complete_lifecycle(api_client: TestClient, awarded_project_id: int):
    contract = api_client.post(f"/projects/{awarded_project_id}/contracts", json={}).json()

    activated = api_client.post(f"/contracts/{contract['id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["status"] == "ACTIVE"

    completed = api_client.post(f"/contracts/{contract['id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"


def test_cannot_complete_a_draft_contract(api_client: TestClient, awarded_project_id: int):
    contract = api_client.post(f"/projects/{awarded_project_id}/contracts", json={}).json()

    response = api_client.post(f"/contracts/{contract['id']}/complete")

    assert response.status_code == 422


def test_terminate_an_active_contract(api_client: TestClient, awarded_project_id: int):
    contract = api_client.post(f"/projects/{awarded_project_id}/contracts", json={}).json()
    api_client.post(f"/contracts/{contract['id']}/activate")

    response = api_client.post(f"/contracts/{contract['id']}/terminate")

    assert response.status_code == 200
    assert response.json()["status"] == "TERMINATED"


def test_cannot_terminate_a_completed_contract(api_client: TestClient, awarded_project_id: int):
    contract = api_client.post(f"/projects/{awarded_project_id}/contracts", json={}).json()
    api_client.post(f"/contracts/{contract['id']}/activate")
    api_client.post(f"/contracts/{contract['id']}/complete")

    response = api_client.post(f"/contracts/{contract['id']}/terminate")

    assert response.status_code == 422


def test_create_contract_without_permission_is_403(api_client: TestClient, awarded_project_id: int):
    api_client.granted.discard("contracts.create")  # type: ignore[attr-defined]

    response = api_client.post(f"/projects/{awarded_project_id}/contracts", json={})

    assert response.status_code == 403
