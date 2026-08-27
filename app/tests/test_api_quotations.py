"""End-to-end tests for the `/quotations` and `/quotation-versions` API
routes -- same pattern as `test_api_clients.py`, via the shared helpers
in `api_test_support.py`.

Quotation creation requires a real `Project`, which requires a real
`Client`, so these tests build that chain through the real API first,
exactly as a real caller would.
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
        "quotations.submit",
        "quotations.edit",
        "quotations.approve",
    }
    yield from make_api_client(engine, granted)
    engine.dispose()


@pytest.fixture
def project_id(api_client: TestClient) -> int:
    client = api_client.post("/clients", json={"name": "Nasser Trading Co."}).json()
    project = api_client.post(
        "/projects", json={"name": "Retail Fit-Out", "client_id": client["id"]}
    ).json()
    return project["id"]


def test_create_quotation_and_list_it(api_client: TestClient, project_id: int):
    response = api_client.post(
        f"/projects/{project_id}/quotations",
        json={"reference_number": "Q-2026-001", "title": "Retail fit-out proposal", "quoted_value": "150000.00"},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["version_number"] == 1
    assert created["status"] == "DRAFT"
    assert created["quotation"]["reference_number"] == "Q-2026-001"

    listing = api_client.get("/quotations")
    assert listing.status_code == 200
    refs = [v["quotation"]["reference_number"] for v in listing.json()]
    assert "Q-2026-001" in refs


def test_create_quotation_for_missing_project_is_404(api_client: TestClient):
    response = api_client.post("/projects/999999/quotations", json={"title": "Should not exist"})
    assert response.status_code == 404


def test_create_quotation_rejects_a_negative_value(api_client: TestClient, project_id: int):
    response = api_client.post(
        f"/projects/{project_id}/quotations", json={"title": "Bad value", "quoted_value": "-1.00"}
    )
    assert response.status_code == 422


def test_get_quotation_and_its_versions(api_client: TestClient, project_id: int):
    version = api_client.post(
        f"/projects/{project_id}/quotations", json={"title": "First cut"}
    ).json()
    quotation_id = version["quotation_id"]

    quotation = api_client.get(f"/quotations/{quotation_id}")
    assert quotation.status_code == 200
    assert quotation.json()["id"] == quotation_id

    versions = api_client.get(f"/quotations/{quotation_id}/versions")
    assert versions.status_code == 200
    assert len(versions.json()) == 1


def test_get_missing_quotation_is_404(api_client: TestClient):
    response = api_client.get("/quotations/999999")
    assert response.status_code == 404


def test_create_a_revision_bumps_the_version_number(api_client: TestClient, project_id: int):
    version = api_client.post(
        f"/projects/{project_id}/quotations", json={"title": "V1"}
    ).json()
    quotation_id = version["quotation_id"]

    revision = api_client.post(
        f"/quotations/{quotation_id}/revisions", json={"quoted_value": "200000.00"}
    )

    assert revision.status_code == 201
    assert revision.json()["version_number"] == 2


def test_submit_and_award_lifecycle(api_client: TestClient, project_id: int):
    version = api_client.post(
        f"/projects/{project_id}/quotations", json={"title": "To be awarded"}
    ).json()
    version_id = version["id"]

    submitted = api_client.post(f"/quotation-versions/{version_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMITTED"

    awarded = api_client.post(f"/quotation-versions/{version_id}/award", json={"contract_value": "175000.00"})
    assert awarded.status_code == 200
    assert awarded.json()["status"] == "WON"

    project = api_client.get(f"/projects/{project_id}").json()
    assert project["status"] == "AWARDED"
    assert project["contract_value"] == "175000.00"


def test_award_a_second_time_is_rejected(api_client: TestClient, project_id: int):
    version = api_client.post(f"/projects/{project_id}/quotations", json={"title": "Once only"}).json()
    version_id = version["id"]
    api_client.post(f"/quotation-versions/{version_id}/award", json={"contract_value": "100.00"})

    response = api_client.post(f"/quotation-versions/{version_id}/award", json={"contract_value": "200.00"})

    assert response.status_code == 422


def test_lose_and_withdraw(api_client: TestClient, project_id: int):
    lost = api_client.post(f"/projects/{project_id}/quotations", json={"title": "Lost one"}).json()
    withdrawn = api_client.post(f"/projects/{project_id}/quotations", json={"title": "Withdrawn one"}).json()

    lost_response = api_client.post(f"/quotation-versions/{lost['id']}/lose")
    withdrawn_response = api_client.post(f"/quotation-versions/{withdrawn['id']}/withdraw")

    assert lost_response.json()["status"] == "LOST"
    assert withdrawn_response.json()["status"] == "WITHDRAWN"


def test_boq_lines_are_empty_for_a_manually_created_quotation(api_client: TestClient, project_id: int):
    version = api_client.post(f"/projects/{project_id}/quotations", json={"title": "No BOQ yet"}).json()

    response = api_client.get(f"/quotation-versions/{version['id']}/boq-lines")

    assert response.status_code == 200
    assert response.json() == []


def test_get_missing_quotation_version_is_404(api_client: TestClient):
    response = api_client.get("/quotation-versions/999999")
    assert response.status_code == 404


def test_submit_without_permission_is_403(api_client: TestClient, project_id: int):
    version = api_client.post(f"/projects/{project_id}/quotations", json={"title": "No perms"}).json()
    api_client.granted.discard("quotations.submit")  # type: ignore[attr-defined]

    response = api_client.post(f"/quotation-versions/{version['id']}/submit")

    assert response.status_code == 403


def test_award_without_permission_is_403(api_client: TestClient, project_id: int):
    version = api_client.post(f"/projects/{project_id}/quotations", json={"title": "No perms"}).json()
    api_client.granted.discard("quotations.approve")  # type: ignore[attr-defined]

    response = api_client.post(
        f"/quotation-versions/{version['id']}/award", json={"contract_value": "100.00"}
    )

    assert response.status_code == 403
