"""Tests for `app.api.auth.SupabaseAdmin`.

Every request is asserted against an `httpx.MockTransport` -- the exact
method/path/body Supabase's Admin API and PostgREST would receive,
matching the existing `SupabaseAuth` test pattern (test_api_auth.py).
Never a real network call.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.api.auth import SupabaseAdmin, SupabaseAdminError, SupabaseUnavailableError


def _admin_with_transport(handler) -> SupabaseAdmin:
    return SupabaseAdmin(
        project_url="https://example.supabase.co",
        service_role_key="test-service-role-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_missing_config_fails_loudly_not_silently() -> None:
    with pytest.raises(SupabaseAdminError, match="not configured"):
        SupabaseAdmin(project_url="", service_role_key="")


def test_create_auth_user_posts_to_admin_users_and_returns_id() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth_header"] = request.headers["authorization"]
        return httpx.Response(200, json={"id": "user-abc-123"})

    admin = _admin_with_transport(handler)
    user_id = admin.create_auth_user(email="jdoe@vinco.local", password="s3cret-pass", full_name="Jane Doe")

    assert user_id == "user-abc-123"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.supabase.co/auth/v1/admin/users"
    assert captured["body"] == {
        "email": "jdoe@vinco.local",
        "password": "s3cret-pass",
        "email_confirm": True,
        "user_metadata": {"full_name": "Jane Doe"},
    }
    assert captured["auth_header"] == "Bearer test-service-role-key"


def test_create_auth_user_raises_on_failure_response() -> None:
    admin = _admin_with_transport(lambda r: httpx.Response(500, json={"msg": "internal error"}))
    with pytest.raises(SupabaseAdminError, match="500"):
        admin.create_auth_user(email="dup@vinco.local", password="s3cret-pass", full_name="Dup")


def test_create_auth_user_gives_a_clean_message_when_the_email_already_exists() -> None:
    """GoTrue reports a duplicate email as a 422 whose body mentions
    "already" -- distinguished from a generic failure with an actionable
    message instead of a raw status/body dump (see auth.py's
    create_auth_user for the version-inconsistency this loose match
    works around)."""
    admin = _admin_with_transport(
        lambda r: httpx.Response(422, json={"msg": "email already registered"})
    )
    with pytest.raises(SupabaseAdminError, match="already exists"):
        admin.create_auth_user(email="dup@vinco.local", password="s3cret-pass", full_name="Dup")


def test_create_auth_user_generic_422_still_uses_generic_message() -> None:
    """A 422 for an unrelated reason (e.g. a malformed field) must not be
    mistaken for the "already exists" case just because it shares a
    status code."""
    admin = _admin_with_transport(lambda r: httpx.Response(422, json={"msg": "weak password"}))
    with pytest.raises(SupabaseAdminError, match="422") as exc_info:
        admin.create_auth_user(email="weak@vinco.local", password="123", full_name="Weak")
    assert "already exists" not in str(exc_info.value)


def test_set_password_puts_to_admin_users_id() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "user-abc-123"})

    admin = _admin_with_transport(handler)
    admin.set_password("user-abc-123", "new-password-1")

    assert captured["method"] == "PUT"
    assert captured["url"] == "https://example.supabase.co/auth/v1/admin/users/user-abc-123"
    assert captured["body"] == {"password": "new-password-1"}


def test_set_password_raises_on_failure_response() -> None:
    admin = _admin_with_transport(lambda r: httpx.Response(500, json={"msg": "internal error"}))
    with pytest.raises(SupabaseAdminError, match="500"):
        admin.set_password("user-abc-123", "new-password-1")


def test_set_email_puts_to_admin_users_id_with_email_confirm() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "user-abc-123"})

    admin = _admin_with_transport(handler)
    admin.set_email("user-abc-123", "the.admin@vinco.local")

    assert captured["method"] == "PUT"
    assert captured["url"] == "https://example.supabase.co/auth/v1/admin/users/user-abc-123"
    assert captured["body"] == {"email": "the.admin@vinco.local", "email_confirm": True}


def test_set_email_raises_on_failure_response() -> None:
    admin = _admin_with_transport(lambda r: httpx.Response(500, json={"msg": "internal error"}))
    with pytest.raises(SupabaseAdminError, match="500"):
        admin.set_email("user-abc-123", "x@vinco.local")


def test_get_user_role_queries_user_roles_by_id_and_returns_the_role() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[{"role": "super_admin"}])

    admin = _admin_with_transport(handler)
    role = admin.get_user_role("user-abc-123")

    assert role == "super_admin"
    assert captured["method"] == "GET"
    assert "rest/v1/user_roles" in captured["url"]
    assert "user_id=eq.user-abc-123" in captured["url"]
    assert "select=role" in captured["url"]


def test_get_user_role_returns_none_when_no_role_row_exists() -> None:
    admin = _admin_with_transport(lambda r: httpx.Response(200, json=[]))
    assert admin.get_user_role("user-abc-123") is None


def test_get_user_role_raises_on_failure_response() -> None:
    admin = _admin_with_transport(lambda r: httpx.Response(500, json={"msg": "internal error"}))
    with pytest.raises(SupabaseAdminError, match="500"):
        admin.get_user_role("user-abc-123")


@pytest.mark.parametrize(
    "banned,expected_duration",
    [(True, "876000h"), (False, "none")],
)
def test_set_banned_sends_correct_ban_duration(banned: bool, expected_duration: str) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "user-abc-123"})

    admin = _admin_with_transport(handler)
    admin.set_banned("user-abc-123", banned=banned)

    assert captured["body"] == {"ban_duration": expected_duration}


def test_set_user_role_deletes_then_inserts_and_sets_scope() -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, str(request.url), body))
        return httpx.Response(200 if request.method != "POST" else 201, json={})

    admin = _admin_with_transport(handler)
    admin.set_user_role("user-abc-123", "employee")

    assert calls[0][0] == "DELETE"
    assert "user_roles" in calls[0][1]
    assert "user_id=eq.user-abc-123" in calls[0][1]

    assert calls[1][0] == "POST"
    assert "user_roles" in calls[1][1]
    assert calls[1][2] == {"user_id": "user-abc-123", "role": "employee"}

    assert calls[2][0] == "POST"
    assert "user_scopes" in calls[2][1]
    assert calls[2][2] == {"user_id": "user-abc-123", "scope": "assigned"}


def test_set_user_role_super_admin_gets_all_scope() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, body))
        return httpx.Response(200 if request.method != "POST" else 201, json={})

    admin = _admin_with_transport(handler)
    admin.set_user_role("user-abc-123", "super_admin")

    scope_call = calls[-1]
    assert scope_call[1] == {"user_id": "user-abc-123", "scope": "all"}


def _network_failure_transport(exc: Exception) -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise exc

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("connection refused"),
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("timed out reading response"),
    ],
)
def test_network_failure_raises_supabase_unavailable_not_a_generic_500(exc: Exception) -> None:
    """None of these ever produced an HTTP response at all -- Part A2's
    "502/503 Supabase/Auth failure" case, distinct from SupabaseAdminError
    (a real response Supabase sent back, e.g. a validation rejection)."""
    admin = SupabaseAdmin(
        project_url="https://example.supabase.co",
        service_role_key="test-service-role-key",
        http_client=_network_failure_transport(exc),
    )
    with pytest.raises(SupabaseUnavailableError):
        admin.create_auth_user(email="jdoe@vinco.local", password="s3cret-pass", full_name="Jane Doe")


def test_network_failure_on_set_password_also_raises_supabase_unavailable() -> None:
    """Not just create_auth_user -- every method routes through the same
    _request helper (see auth.py), so this is a property of SupabaseAdmin
    as a whole, not one call site."""
    admin = SupabaseAdmin(
        project_url="https://example.supabase.co",
        service_role_key="test-service-role-key",
        http_client=_network_failure_transport(httpx.ConnectError("connection refused")),
    )
    with pytest.raises(SupabaseUnavailableError):
        admin.set_password("user-abc-123", "new-password-1")


def test_set_user_role_raises_clearly_when_role_value_is_rejected() -> None:
    """Simulates assigning a role the app_role Postgres enum doesn't have
    yet (e.g. 'super_user' before the one-time migration SQL runs)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(400, json={"message": 'invalid input value for enum app_role: "super_user"'})

    admin = _admin_with_transport(handler)
    with pytest.raises(SupabaseAdminError, match="doesn't exist yet in the app_role"):
        admin.set_user_role("user-abc-123", "super_user")
