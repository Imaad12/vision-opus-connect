"""End-to-end tests for the native VINCO `/users` API routes.

Same TestClient + dependency_overrides pattern as test_api_clients.py:
`require_permission`'s own logic runs for real (401 vs. 403 vs. allowed),
only the network boundaries (Supabase auth check, Supabase admin API)
are replaced with controllable fakes.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.api.auth import AuthenticatedUser, SupabaseAdminError
from app.api.deps import get_current_user, get_db, get_supabase_admin, get_supabase_auth
from app.api.main import create_app
from app.database.base import Base


class _FakeSupabaseAuth:
    def __init__(self, granted: set[str]) -> None:
        self.granted = granted

    def check_permission(self, _user: AuthenticatedUser, permission: str) -> bool:
        return permission in self.granted


class _FakeSupabaseAdmin:
    """Records every call instead of talking to Supabase -- `SupabaseAdmin`
    itself is covered separately, by real HTTP-shape assertions, in
    test_supabase_admin.py."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.roles_set: list[tuple[str, str]] = []
        self.banned: list[tuple[str, bool]] = []
        self.passwords_reset: list[tuple[str, str]] = []
        self._next_id = 1
        self.reject_role: str | None = None

    def create_auth_user(self, *, email: str, password: str, full_name: str) -> str:
        user_id = f"fake-user-{self._next_id}"
        self._next_id += 1
        self.created.append({"id": user_id, "email": email, "password": password, "full_name": full_name})
        return user_id

    def set_user_role(self, user_id: str, role: str) -> None:
        if role == self.reject_role:
            raise SupabaseAdminError(
                f"role {role!r} doesn't exist yet in the app_role Postgres enum"
            )
        self.roles_set.append((user_id, role))

    def set_banned(self, user_id: str, *, banned: bool) -> None:
        self.banned.append((user_id, banned))

    def set_password(self, user_id: str, password: str) -> None:
        self.passwords_reset.append((user_id, password))


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
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
def fake_admin() -> _FakeSupabaseAdmin:
    return _FakeSupabaseAdmin()


@pytest.fixture
def api_client(engine: Engine, fake_admin: _FakeSupabaseAdmin):
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    state = {"granted": {"admin.users", "admin.roles"}}

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
        id="admin-caller", email="admin@example.com", token="fake-token", claims={}
    )
    app.dependency_overrides[get_supabase_auth] = lambda: _FakeSupabaseAuth(state["granted"])
    app.dependency_overrides[get_supabase_admin] = lambda: fake_admin

    with TestClient(app) as client:
        client.state = state  # type: ignore[attr-defined]
        yield client


def _create_payload(**overrides) -> dict:
    payload = {
        "username": "jdoe",
        "display_name": "Jane Doe",
        "password": "correct-horse-battery",
        "role": "employee",
        "is_active": True,
    }
    payload.update(overrides)
    return payload


def test_create_user_success(api_client: TestClient, fake_admin: _FakeSupabaseAdmin):
    response = api_client.post("/users", json=_create_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "jdoe"
    assert body["role"] == "employee"
    assert body["is_active"] is True

    assert len(fake_admin.created) == 1
    assert fake_admin.created[0]["email"] == "jdoe@vinco.local"
    assert fake_admin.roles_set == [(body["id"], "employee")]
    # Never echoed back
    assert "password" not in body


def test_create_user_response_never_contains_password(api_client: TestClient):
    response = api_client.post("/users", json=_create_payload())
    assert "correct-horse-battery" not in response.text


def test_create_user_duplicate_username_is_422(api_client: TestClient):
    first = api_client.post("/users", json=_create_payload())
    assert first.status_code == 201

    second = api_client.post("/users", json=_create_payload(display_name="Someone Else"))
    assert second.status_code == 422
    assert "already taken" in second.json()["detail"]


def test_create_user_unknown_role_is_422(api_client: TestClient):
    response = api_client.post("/users", json=_create_payload(role="wizard"))
    assert response.status_code == 422


def test_create_inactive_user_bans_immediately(api_client: TestClient, fake_admin: _FakeSupabaseAdmin):
    response = api_client.post("/users", json=_create_payload(is_active=False))
    assert response.status_code == 201
    body = response.json()
    assert body["is_active"] is False
    assert fake_admin.banned == [(body["id"], True)]


def test_list_users(api_client: TestClient):
    api_client.post("/users", json=_create_payload())
    api_client.post("/users", json=_create_payload(username="asmith", display_name="Alex Smith"))

    response = api_client.get("/users")
    assert response.status_code == 200
    usernames = {u["username"] for u in response.json()}
    assert usernames == {"jdoe", "asmith"}


def test_update_user_active_status_calls_ban(api_client: TestClient, fake_admin: _FakeSupabaseAdmin):
    created = api_client.post("/users", json=_create_payload()).json()

    response = api_client.put(f"/users/{created['id']}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert (created["id"], True) in fake_admin.banned


def test_update_user_display_name(api_client: TestClient):
    created = api_client.post("/users", json=_create_payload()).json()

    response = api_client.put(f"/users/{created['id']}", json={"display_name": "Jane D. Doe"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Jane D. Doe"


def test_update_missing_user_is_404(api_client: TestClient):
    response = api_client.put("/users/does-not-exist", json={"display_name": "X"})
    assert response.status_code == 404


def test_update_user_role(api_client: TestClient, fake_admin: _FakeSupabaseAdmin):
    created = api_client.post("/users", json=_create_payload()).json()

    response = api_client.put(f"/users/{created['id']}/role", json={"role": "admin"})
    assert response.status_code == 200
    # VINCO's "admin" label maps onto the existing "general_manager"
    # Supabase role -- see user_service.ROLE_TO_SUPABASE_ROLE.
    assert response.json()["role"] == "admin"
    assert (created["id"], "general_manager") in fake_admin.roles_set


def test_update_role_to_not_yet_migrated_role_is_422(api_client: TestClient, fake_admin: _FakeSupabaseAdmin):
    created = api_client.post("/users", json=_create_payload()).json()
    fake_admin.reject_role = "super_user"

    response = api_client.put(f"/users/{created['id']}/role", json={"role": "super_user"})
    assert response.status_code == 422
    assert "app_role" in response.json()["detail"]


def test_reset_password(api_client: TestClient, fake_admin: _FakeSupabaseAdmin):
    created = api_client.post("/users", json=_create_payload()).json()

    response = api_client.post(f"/users/{created['id']}/reset-password", json={"password": "new-password-99"})
    assert response.status_code == 204
    assert (created["id"], "new-password-99") in fake_admin.passwords_reset


def test_reset_password_response_never_contains_password(api_client: TestClient):
    created = api_client.post("/users", json=_create_payload()).json()
    response = api_client.post(f"/users/{created['id']}/reset-password", json={"password": "super-secret-value"})
    assert "super-secret-value" not in response.text


# ---- Permission enforcement (Phase 17's explicit security matrix) ----


def test_list_users_without_admin_users_permission_is_403(api_client: TestClient):
    api_client.state["granted"].discard("admin.users")  # type: ignore[attr-defined]
    response = api_client.get("/users")
    assert response.status_code == 403


def test_create_user_without_admin_users_permission_is_403(api_client: TestClient):
    api_client.state["granted"].discard("admin.users")  # type: ignore[attr-defined]
    response = api_client.post("/users", json=_create_payload())
    assert response.status_code == 403


def test_role_change_requires_admin_roles_even_with_admin_users(api_client: TestClient):
    created = api_client.post("/users", json=_create_payload()).json()
    api_client.state["granted"].discard("admin.roles")  # type: ignore[attr-defined]
    # admin.users alone (still granted) must not be enough for a role change.
    response = api_client.put(f"/users/{created['id']}/role", json={"role": "admin"})
    assert response.status_code == 403


def test_missing_bearer_token_is_401(engine: Engine, fake_admin: _FakeSupabaseAdmin):
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: iter([factory()])
    app.dependency_overrides[get_supabase_auth] = lambda: _FakeSupabaseAuth(set())
    app.dependency_overrides[get_supabase_admin] = lambda: fake_admin

    with TestClient(app) as client:
        response = client.get("/users")

    assert response.status_code == 401
