"""Full /clients CRUD round-trip against a REAL, Alembic-migrated
PostgreSQL database -- the one thing no other test proves.

`test_api_clients.py` proves the route/permission/service code is
correct against an in-memory SQLite schema built by
`Base.metadata.create_all()`. `test_migrations.py` proves the real
Alembic chain reaches head on a real Postgres database. Neither proves
the two actually work *together*: that the schema the documented
`stamp` + `upgrade head` procedure produces is the schema the API code
actually expects. This closes that gap directly, on the exact
production-shaped path traced from the "Load failed for customers"
report: POST /clients (create) -> GET /clients (list) -> GET /clients/{id}
(read) -> PUT /clients/{id} (update), all against a database that only
exists because Alembic ran for real, using FastAPI's real permission
dependency (only the Supabase network boundary is faked, same pattern as
test_api_clients.py).

Skipped entirely unless VISION_TEST_POSTGRES_URL is set (same convention
as test_migrations.py / test_postgres_compat.py) -- this drops and
recreates a schema and must never run against a shared or production
database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.api.auth import AuthenticatedUser
from app.api.deps import get_current_user, get_db, get_supabase_auth
from app.api.main import create_app
from app.database.session import get_engine

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSTGRES_TEST_URL = os.environ.get("VISION_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="VISION_TEST_POSTGRES_URL not set -- skipping real-Postgres API round-trip test",
)

STAMP_BEFORE_SQUASH = "cb86207a716e"
SCHEMA = "vinco"


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["VISION_DATABASE_URL"] = POSTGRES_TEST_URL or ""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result


class _FakeSupabaseAuth:
    def __init__(self, granted: set[str]) -> None:
        self.granted = granted

    def check_permission(self, _user: AuthenticatedUser, permission: str) -> bool:
        return permission in self.granted


@pytest.fixture
def migrated_api_client() -> Generator[TestClient, None, None]:
    engine = create_engine(POSTGRES_TEST_URL, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
            conn.commit()
    finally:
        engine.dispose()

    _run_alembic("stamp", STAMP_BEFORE_SQUASH)
    _run_alembic("upgrade", "head")

    # The app's own get_engine() -- not a bare create_engine() -- because
    # it's what actually pins the connection's search_path to the
    # `vinco` schema (app/database/schema_isolation.py). A bare engine
    # defaults to Postgres's own search_path ("$user", public), which
    # doesn't have `clients` at all: caught exactly this way on the
    # first version of this test (UndefinedTable: relation "clients"
    # does not exist), a reminder that this pin is a real, load-bearing
    # part of every request, not incidental.
    real_engine = get_engine(POSTGRES_TEST_URL)
    factory = sessionmaker(bind=real_engine, expire_on_commit=False, future=True)

    def _get_db_override():
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
    app.dependency_overrides[get_supabase_auth] = lambda: _FakeSupabaseAuth(
        {"customers.view", "customers.create", "customers.edit"}
    )

    with TestClient(app) as client:
        yield client

    real_engine.dispose()


def test_full_client_crud_round_trip_on_a_really_migrated_database(
    migrated_api_client: TestClient,
) -> None:
    create_response = migrated_api_client.post(
        "/clients",
        json={
            "name": "Real-Postgres Test Client",
            "contact_name": "Jamie Test",
            "contact_email": "jamie@example.com",
        },
    )
    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    assert created["name"] == "Real-Postgres Test Client"
    client_id = created["id"]

    list_response = migrated_api_client.get("/clients")
    assert list_response.status_code == 200, list_response.text
    names = [c["name"] for c in list_response.json()]
    assert "Real-Postgres Test Client" in names

    get_response = migrated_api_client.get(f"/clients/{client_id}")
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["contact_email"] == "jamie@example.com"

    update_response = migrated_api_client.put(
        f"/clients/{client_id}", json={"name": "Renamed Client", "contact_name": "Jamie Test"}
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["name"] == "Renamed Client"
