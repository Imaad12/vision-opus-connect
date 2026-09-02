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
from app.models import AppUser, Employee


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


def _seed_employee(engine: Engine, *, full_name: str = "Sam Employee") -> int:
    """Inserts one HR roster row directly (bypassing the /employees API,
    which is out of scope for these tests) and returns its id, for tests
    that need a real employee to link a VINCO login to."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        employee = Employee(full_name=full_name)
        session.add(employee)
        session.commit()
        return employee.id


def _seed_app_user(
    engine: Engine, *, id: str, username: str, role: str = "employee", is_active: bool = True
) -> None:
    """Inserts one app_users row directly with a caller-chosen id -- for
    tests that need the row to belong to whichever id `get_current_user`
    is overridden to return (record-login tests), rather than whatever
    id `_FakeSupabaseAdmin.create_auth_user` would generate."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        session.add(
            AppUser(id=id, username=username, display_name=username, role=role, is_active=is_active)
        )
        session.commit()


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


# ---- Employee -> VINCO login linking ----


def test_create_user_links_employee(api_client: TestClient, engine: Engine, fake_admin: _FakeSupabaseAdmin):
    employee_id = _seed_employee(engine, full_name="Priya Patel")

    response = api_client.post("/users", json=_create_payload(employee_id=employee_id))
    assert response.status_code == 201, response.text
    assert response.json()["employee_id"] == employee_id

    # Round-trips through list_users too, not just the create response.
    listed = api_client.get("/users").json()
    assert listed[0]["employee_id"] == employee_id


def test_create_user_without_employee_id_is_unlinked(api_client: TestClient):
    response = api_client.post("/users", json=_create_payload())
    assert response.status_code == 201
    assert response.json()["employee_id"] is None


def test_create_user_unknown_employee_id_is_422(api_client: TestClient):
    response = api_client.post("/users", json=_create_payload(employee_id=999999))
    assert response.status_code == 422
    assert "not found" in response.json()["detail"]


def test_create_user_duplicate_employee_link_is_422(api_client: TestClient, engine: Engine):
    employee_id = _seed_employee(engine)

    first = api_client.post("/users", json=_create_payload(employee_id=employee_id))
    assert first.status_code == 201

    second = api_client.post(
        "/users", json=_create_payload(username="other", display_name="Other Person", employee_id=employee_id)
    )
    assert second.status_code == 422
    assert "already has a VINCO login" in second.json()["detail"]


def test_create_user_rejected_employee_link_does_not_create_orphaned_auth_account(
    api_client: TestClient, fake_admin: _FakeSupabaseAdmin
):
    """A bad employee_id must fail before any Supabase Auth call, not
    after -- otherwise a rejected request would still leave behind a
    real (orphaned) Supabase Auth identity with no app_users row."""
    response = api_client.post("/users", json=_create_payload(employee_id=999999))
    assert response.status_code == 422
    assert fake_admin.created == []


def test_create_user_role_assigned_with_employee_link(
    api_client: TestClient, engine: Engine, fake_admin: _FakeSupabaseAdmin
):
    employee_id = _seed_employee(engine)

    response = api_client.post("/users", json=_create_payload(employee_id=employee_id, role="admin"))
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "admin"
    assert body["employee_id"] == employee_id
    # VINCO's "admin" label still maps onto the real Supabase role, exactly
    # as it does for an unlinked user -- linking an employee changes
    # nothing about role enforcement.
    assert (body["id"], "general_manager") in fake_admin.roles_set


def test_create_user_without_admin_users_permission_cannot_link_employee(
    api_client: TestClient, engine: Engine
):
    """The same permission gate covers the employee-linked path -- an
    unauthorized caller can't provision VINCO access for any employee,
    linked or not."""
    employee_id = _seed_employee(engine)
    api_client.state["granted"].discard("admin.users")  # type: ignore[attr-defined]
    response = api_client.post("/users", json=_create_payload(employee_id=employee_id))
    assert response.status_code == 403


# ---- Employee link/unlink after creation (Part 8/9) ----


def test_link_employee_to_existing_user(api_client: TestClient, engine: Engine):
    employee_id = _seed_employee(engine, full_name="Later Linked")
    created = api_client.post("/users", json=_create_payload()).json()
    assert created["employee_id"] is None

    response = api_client.put(f"/users/{created['id']}/employee-link", json={"employee_id": employee_id})
    assert response.status_code == 200
    assert response.json()["employee_id"] == employee_id


def test_unlink_employee_from_user(api_client: TestClient, engine: Engine):
    employee_id = _seed_employee(engine)
    created = api_client.post("/users", json=_create_payload(employee_id=employee_id)).json()
    assert created["employee_id"] == employee_id

    response = api_client.put(f"/users/{created['id']}/employee-link", json={"employee_id": None})
    assert response.status_code == 200
    assert response.json()["employee_id"] is None


def test_link_employee_already_linked_to_another_user_is_422(api_client: TestClient, engine: Engine):
    employee_id = _seed_employee(engine)
    api_client.post("/users", json=_create_payload(employee_id=employee_id))
    other = api_client.post("/users", json=_create_payload(username="second", display_name="Second")).json()

    response = api_client.put(f"/users/{other['id']}/employee-link", json={"employee_id": employee_id})
    assert response.status_code == 422
    assert "already has a VINCO login" in response.json()["detail"]


def test_relinking_user_to_same_employee_it_already_has_is_allowed(api_client: TestClient, engine: Engine):
    """Setting the employee_id a user already has must not trip the
    duplicate-link check against its own existing row."""
    employee_id = _seed_employee(engine)
    created = api_client.post("/users", json=_create_payload(employee_id=employee_id)).json()

    response = api_client.put(f"/users/{created['id']}/employee-link", json={"employee_id": employee_id})
    assert response.status_code == 200
    assert response.json()["employee_id"] == employee_id


def test_employee_link_without_admin_users_permission_is_403(api_client: TestClient, engine: Engine):
    # Seeded directly (not via POST /users): an earlier admin.users-gated
    # call from this same caller would cache that permission as granted
    # for the deliberate short TTL (see permission_cache.py), which would
    # then mask the discard below and defeat this exact test.
    employee_id = _seed_employee(engine)
    _seed_app_user(engine, id="target-user", username="target")
    api_client.state["granted"].discard("admin.users")  # type: ignore[attr-defined]

    response = api_client.put("/users/target-user/employee-link", json={"employee_id": employee_id})
    assert response.status_code == 403


# ---- Last active Super Admin protection (Part 13) ----


def test_deactivating_the_only_active_super_admin_is_blocked(api_client: TestClient):
    boss = api_client.post(
        "/users", json=_create_payload(username="boss", display_name="Boss", role="super_admin")
    ).json()

    response = api_client.put(f"/users/{boss['id']}", json={"is_active": False})
    assert response.status_code == 422
    assert "last active Super Admin" in response.json()["detail"]


def test_deactivating_a_super_admin_is_allowed_when_another_is_active(api_client: TestClient):
    boss1 = api_client.post(
        "/users", json=_create_payload(username="boss1", display_name="Boss 1", role="super_admin")
    ).json()
    api_client.post("/users", json=_create_payload(username="boss2", display_name="Boss 2", role="super_admin"))

    response = api_client.put(f"/users/{boss1['id']}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_demoting_the_only_active_super_admin_is_blocked(api_client: TestClient):
    boss = api_client.post(
        "/users", json=_create_payload(username="boss", display_name="Boss", role="super_admin")
    ).json()

    response = api_client.put(f"/users/{boss['id']}/role", json={"role": "admin"})
    assert response.status_code == 422
    assert "last active Super Admin" in response.json()["detail"]


def test_demoting_a_super_admin_is_allowed_when_another_is_active(api_client: TestClient):
    boss1 = api_client.post(
        "/users", json=_create_payload(username="boss1", display_name="Boss 1", role="super_admin")
    ).json()
    api_client.post("/users", json=_create_payload(username="boss2", display_name="Boss 2", role="super_admin"))

    response = api_client.put(f"/users/{boss1['id']}/role", json={"role": "admin"})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_reactivating_a_deactivated_super_admin_is_never_blocked(api_client: TestClient):
    """The guard only ever blocks the direction that reduces the active
    count -- reactivating can only increase it."""
    boss = api_client.post(
        "/users",
        json=_create_payload(username="boss", display_name="Boss", role="super_admin", is_active=False),
    ).json()

    response = api_client.put(f"/users/{boss['id']}", json={"is_active": True})
    assert response.status_code == 200
    assert response.json()["is_active"] is True


def test_demoting_an_already_inactive_super_admin_is_allowed(api_client: TestClient):
    """An inactive Super Admin doesn't count toward "at least one active"
    -- demoting them further doesn't reduce anything that was counted."""
    boss = api_client.post(
        "/users",
        json=_create_payload(username="boss", display_name="Boss", role="super_admin", is_active=False),
    ).json()

    response = api_client.put(f"/users/{boss['id']}/role", json={"role": "admin"})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_deactivating_a_non_super_admin_is_never_blocked(api_client: TestClient):
    """The guard is scoped to the Super Admin role only -- deactivating
    the sole Admin/Employee/Super User account is unaffected."""
    plain = api_client.post("/users", json=_create_payload()).json()

    response = api_client.put(f"/users/{plain['id']}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False


# ---- Login tracking (Part 2/3/4: real, not fabricated, last-login data) ----


def test_record_login_sets_last_login_at_for_the_caller(api_client: TestClient, engine: Engine):
    _seed_app_user(engine, id="admin-caller", username="whoami")

    response = api_client.post("/users/me/record-login")
    assert response.status_code == 204

    listed = api_client.get("/users").json()
    mine = next(u for u in listed if u["id"] == "admin-caller")
    assert mine["last_login_at"] is not None


def test_record_login_is_a_noop_when_caller_has_no_app_user_row(api_client: TestClient):
    # The fixture's default caller ("admin-caller") has no app_users row
    # unless a test seeds one -- must not 404/500, just succeed quietly.
    response = api_client.post("/users/me/record-login")
    assert response.status_code == 204


def test_record_login_requires_no_special_permission(engine: Engine, fake_admin: _FakeSupabaseAdmin):
    """Every authenticated user may record their own login -- unlike
    every other /users route, no admin.users/admin.roles is required."""
    _seed_app_user(engine, id="plain-caller", username="plain")
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _get_db_override() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="plain-caller", email="plain@example.com", token="fake-token", claims={}
    )
    app.dependency_overrides[get_supabase_auth] = lambda: _FakeSupabaseAuth(set())
    app.dependency_overrides[get_supabase_admin] = lambda: fake_admin

    with TestClient(app) as client:
        response = client.post("/users/me/record-login")

    assert response.status_code == 204


def test_record_login_requires_a_bearer_token(engine: Engine, fake_admin: _FakeSupabaseAdmin):
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: iter([factory()])
    app.dependency_overrides[get_supabase_auth] = lambda: _FakeSupabaseAuth(set())
    app.dependency_overrides[get_supabase_admin] = lambda: fake_admin

    with TestClient(app) as client:
        response = client.post("/users/me/record-login")

    assert response.status_code == 401
