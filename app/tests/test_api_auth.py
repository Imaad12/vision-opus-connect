"""Tests for `app.api.auth.SupabaseAuth`.

`verify_token` is tested with a real RSA keypair and real signature
verification via PyJWT -- only the JWKS *network fetch* is stubbed
(`SupabaseAuth` never talks to a real Supabase project in tests).
`check_permission` is tested against an `httpx.MockTransport`, so the
exact request Supabase would receive (method, path, headers, body) is
asserted directly rather than assumed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.auth import AuthError, SupabaseAuth


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _make_token(private_key, *, claims: dict) -> str:
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


@dataclass
class _FakeSigningKey:
    key: object


def _auth_with_stubbed_jwks(public_key, *, http_client: httpx.Client | None = None) -> SupabaseAuth:
    auth = SupabaseAuth(
        project_url="https://example.supabase.co",
        anon_key="test-anon-key",
        http_client=http_client,
    )
    auth._jwks_client.get_signing_key_from_jwt = lambda _token: _FakeSigningKey(key=public_key)
    return auth


def test_verify_token_accepts_a_validly_signed_unexpired_token(rsa_keypair):
    private_key, public_key = rsa_keypair
    token = _make_token(
        private_key,
        claims={"sub": "user-123", "email": "a@example.com", "aud": "authenticated", "exp": int(time.time()) + 3600},
    )
    auth = _auth_with_stubbed_jwks(public_key)

    user = auth.verify_token(token)

    assert user.id == "user-123"
    assert user.email == "a@example.com"
    assert user.token == token


def test_verify_token_rejects_an_expired_token(rsa_keypair):
    private_key, public_key = rsa_keypair
    token = _make_token(
        private_key,
        claims={"sub": "user-123", "aud": "authenticated", "exp": int(time.time()) - 10},
    )
    auth = _auth_with_stubbed_jwks(public_key)

    with pytest.raises(AuthError):
        auth.verify_token(token)


def test_verify_token_rejects_a_token_signed_by_a_different_key(rsa_keypair):
    _private_key, public_key = rsa_keypair
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_token(
        other_private_key,
        claims={"sub": "user-123", "aud": "authenticated", "exp": int(time.time()) + 3600},
    )
    auth = _auth_with_stubbed_jwks(public_key)

    with pytest.raises(AuthError):
        auth.verify_token(token)


def test_verify_token_rejects_the_wrong_audience(rsa_keypair):
    private_key, public_key = rsa_keypair
    token = _make_token(
        private_key,
        claims={"sub": "user-123", "aud": "some-other-service", "exp": int(time.time()) + 3600},
    )
    auth = _auth_with_stubbed_jwks(public_key)

    with pytest.raises(AuthError):
        auth.verify_token(token)


def test_verify_token_rejects_a_token_missing_sub(rsa_keypair):
    private_key, public_key = rsa_keypair
    token = _make_token(
        private_key,
        claims={"aud": "authenticated", "exp": int(time.time()) + 3600},
    )
    auth = _auth_with_stubbed_jwks(public_key)

    with pytest.raises(AuthError):
        auth.verify_token(token)


def test_check_permission_forwards_the_users_own_token_and_returns_true(rsa_keypair):
    _private_key, public_key = rsa_keypair
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = request.read()
        return httpx.Response(200, json=True)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    auth = _auth_with_stubbed_jwks(public_key, http_client=http_client)
    from app.api.auth import AuthenticatedUser

    user = AuthenticatedUser(id="user-123", email=None, token="the-users-token", claims={})

    result = auth.check_permission(user, "customers.view")

    assert result is True
    assert captured["url"] == "https://example.supabase.co/rest/v1/rpc/can"
    assert captured["headers"]["authorization"] == "Bearer the-users-token"
    assert captured["headers"]["apikey"] == "test-anon-key"
    assert b'"customers.view"' in captured["body"]


def test_check_permission_returns_false_when_supabase_says_no(rsa_keypair):
    _private_key, public_key = rsa_keypair
    http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=False)))
    auth = _auth_with_stubbed_jwks(public_key, http_client=http_client)
    from app.api.auth import AuthenticatedUser

    user = AuthenticatedUser(id="user-123", email=None, token="tok", claims={})

    assert auth.check_permission(user, "admin.settings") is False


def test_check_permission_raises_on_a_non_200_response(rsa_keypair):
    _private_key, public_key = rsa_keypair
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="db error"))
    )
    auth = _auth_with_stubbed_jwks(public_key, http_client=http_client)
    from app.api.auth import AuthenticatedUser

    user = AuthenticatedUser(id="user-123", email=None, token="tok", claims={})

    with pytest.raises(AuthError):
        auth.check_permission(user, "admin.settings")


def test_supabase_auth_refuses_to_construct_without_configuration():
    with pytest.raises(AuthError):
        SupabaseAuth(project_url="", anon_key="")
