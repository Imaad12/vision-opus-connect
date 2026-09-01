"""End-to-end tests for the `/clients` API routes.

These exercise the real route -> `client_service` -> SQLAlchemy path
against an in-memory database (same pattern as `conftest.py`'s
`db_session` fixture). Only the Supabase boundary (`get_current_user`,
`get_supabase_auth`) is replaced with a controllable fake, via FastAPI's
`dependency_overrides` -- so `require_permission`'s own logic (401 vs.
403 vs. allowed) still runs for real, only the network call it would
otherwise make to Supabase is stubbed.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.api.auth import AuthenticatedUser
from app.api.deps import get_current_user, get_db, get_supabase_auth
from app.api.main import create_app
from app.database.base import Base


class _FakeSupabaseAuth:
    """Grants exactly the permissions a test configures, and never makes a
    network call -- `check_permission` is the only method the API layer
    calls on it after `get_current_user` has already run."""

    def __init__(self, granted: set[str]) -> None:
        self.granted = granted

    def check_permission(self, _user: AuthenticatedUser, permission: str) -> bool:
        return permission in self.granted


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    # `check_same_thread=False` + `StaticPool` (one connection, reused) --
    # required because Starlette's TestClient runs synchronous route
    # handlers in a worker thread, and a bare `sqlite:///:memory:`
    # database is otherwise a fresh, empty, thread-local database per
    # connection (see SQLAlchemy's SQLite in-memory testing docs).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def api_client(engine: Engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    state = {"granted": {"customers.view", "customers.create", "customers.edit"}}

    def _get_db_override() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="user-1", email="tester@example.com", token="fake-token", claims={}
    )
    app.dependency_overrides[get_supabase_auth] = lambda: _FakeSupabaseAuth(state["granted"])

    with TestClient(app) as client:
        client.state = state  # type: ignore[attr-defined]
        yield client


def test_create_and_list_clients(api_client: TestClient):
    response = api_client.post("/clients", json={"name": "Acme Contracting"})
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Acme Contracting"
    assert created["id"] is not None

    listing = api_client.get("/clients")
    assert listing.status_code == 200
    names = [c["name"] for c in listing.json()]
    assert "Acme Contracting" in names


def test_get_single_client(api_client: TestClient):
    created = api_client.post("/clients", json={"name": "Beta LLC"}).json()

    response = api_client.get(f"/clients/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Beta LLC"


def test_get_missing_client_is_404(api_client: TestClient):
    response = api_client.get("/clients/999999")
    assert response.status_code == 404


def test_create_client_without_a_name_is_422(api_client: TestClient):
    response = api_client.post("/clients", json={"name": "   "})
    assert response.status_code == 422


def test_update_client(api_client: TestClient):
    created = api_client.post("/clients", json={"name": "Gamma Co"}).json()

    response = api_client.put(
        f"/clients/{created['id']}", json={"name": "Gamma Co (renamed)", "contact_name": "Sara"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Gamma Co (renamed)"
    assert response.json()["contact_name"] == "Sara"


def test_list_clients_without_view_permission_is_403(api_client: TestClient):
    api_client.state["granted"].discard("customers.view")  # type: ignore[attr-defined]

    response = api_client.get("/clients")

    assert response.status_code == 403


def test_create_client_without_create_permission_is_403(api_client: TestClient):
    api_client.state["granted"].discard("customers.create")  # type: ignore[attr-defined]

    response = api_client.post("/clients", json={"name": "Should Not Be Created"})

    assert response.status_code == 403


def test_missing_bearer_token_is_401(engine: Engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    app = create_app()
    # Deliberately leave get_current_user un-overridden here so the real
    # dependency runs and rejects the request for lacking a token.
    # get_db and get_supabase_auth are still overridden so this test
    # never touches the real project database or a real Supabase project,
    # regardless of FastAPI's dependency-resolution order.
    app.dependency_overrides[get_db] = lambda: iter([factory()])
    app.dependency_overrides[get_supabase_auth] = lambda: _FakeSupabaseAuth(set())

    with TestClient(app) as client:
        response = client.get("/clients")

    assert response.status_code == 401


def test_health_endpoint_requires_no_auth():
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
