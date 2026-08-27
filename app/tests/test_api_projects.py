"""End-to-end tests for the `/projects` API routes -- same pattern as
`test_api_clients.py`, via the shared helpers in `api_test_support.py`.

Project creation requires a valid `client_id`, so these tests create a
client through the real `/clients` API first (exactly how a real caller
would), rather than reaching around the API into the database directly.
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
        "projects.edit",
    }
    yield from make_api_client(engine, granted)
    engine.dispose()


@pytest.fixture
def client_id(api_client: TestClient) -> int:
    response = api_client.post("/clients", json={"name": "Al Fahad Holding"})
    assert response.status_code == 201
    return response.json()["id"]


def test_create_and_list_projects(api_client: TestClient, client_id: int):
    response = api_client.post("/projects", json={"name": "Warehouse Fit-Out", "client_id": client_id})
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Warehouse Fit-Out"
    assert created["client_id"] == client_id
    assert created["status"] == "LEAD"

    listing = api_client.get("/projects")
    assert listing.status_code == 200
    names = [p["name"] for p in listing.json()]
    assert "Warehouse Fit-Out" in names


def test_create_project_without_a_valid_client_is_422(api_client: TestClient):
    response = api_client.post("/projects", json={"name": "Orphan Project", "client_id": 999999})
    assert response.status_code == 422


def test_get_single_project(api_client: TestClient, client_id: int):
    created = api_client.post(
        "/projects", json={"name": "Villa Renovation", "client_id": client_id}
    ).json()

    response = api_client.get(f"/projects/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Villa Renovation"


def test_get_missing_project_is_404(api_client: TestClient):
    response = api_client.get("/projects/999999")
    assert response.status_code == 404


def test_update_project(api_client: TestClient, client_id: int):
    created = api_client.post(
        "/projects", json={"name": "Office Tower", "client_id": client_id}
    ).json()

    response = api_client.put(
        f"/projects/{created['id']}",
        json={"name": "Office Tower Phase 1", "client_id": client_id, "status": "TENDERING"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Office Tower Phase 1"
    assert body["status"] == "TENDERING"


def test_update_project_rejects_completion_before_start_date(api_client: TestClient, client_id: int):
    created = api_client.post(
        "/projects", json={"name": "Bridge Works", "client_id": client_id}
    ).json()

    response = api_client.put(
        f"/projects/{created['id']}",
        json={
            "name": "Bridge Works",
            "client_id": client_id,
            "start_date": "2026-06-01",
            "planned_completion_date": "2026-01-01",
        },
    )
    assert response.status_code == 422


def test_list_projects_filters_by_status(api_client: TestClient, client_id: int):
    api_client.post("/projects", json={"name": "Lead Project", "client_id": client_id})
    api_client.post(
        "/projects", json={"name": "Tendering Project", "client_id": client_id, "status": "TENDERING"}
    )

    response = api_client.get("/projects", params={"status_filter": "TENDERING"})

    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert names == ["Tendering Project"]


def test_list_projects_without_view_permission_is_403(api_client: TestClient):
    api_client.granted.discard("projects.view")  # type: ignore[attr-defined]

    response = api_client.get("/projects")

    assert response.status_code == 403
