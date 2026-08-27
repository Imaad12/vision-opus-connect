"""Identity and permission verification for the API layer.

This backend does not have its own user/role/permission model, and this
module deliberately does not build one. Identity and RBAC already exist,
live, in the Supabase project the VINCO frontend authenticates against
(see the frontend's `supabase/migrations/*.sql`: `user_roles`,
`role_permissions`, `user_permissions`, `user_scopes`, and the
`has_permission`/`can` SQL functions). Duplicating that model here would
create two independently-editable copies of "who can do what" -- exactly
the kind of drift this codebase's safety conventions exist to prevent.

Instead:
  * `SupabaseAuth.verify_token` checks the bearer token's signature against
    the same Supabase project's JWKS and extracts the caller's identity.
    Nothing about *authorization* is decided here -- only "is this a
    genuine, unexpired token, and who does it belong to".
  * `SupabaseAuth.check_permission` asks Supabase's own `can(_perm)`
    Postgres function, over PostgREST, using the caller's own verified
    token as the request's bearer credential. `can()` reads `auth.uid()`
    from that token via Postgres's request context and evaluates the
    exact same role/permission/override rows the frontend's Row-Level
    Security already enforces. This backend never re-implements that
    logic and never sees a service-role key.

See API_ARCHITECTURE.md for the full rationale and the migration path
away from Supabase once VINCO has its own identity store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import jwt

__all__ = ["AuthenticatedUser", "AuthError", "SupabaseAuth"]


class AuthError(Exception):
    """Raised when a bearer token fails verification or a permission check
    cannot be completed. Callers map this to HTTP 401, never to 403 --
    "we couldn't verify who you are" is a different failure than "you are
    verified and not allowed", and the two must never be conflated."""


@dataclass(frozen=True)
class AuthenticatedUser:
    """The identity carried by a verified Supabase access token.

    `token` is retained (not just the decoded claims) because permission
    checks must be re-asserted to Supabase using the caller's own token,
    never assumed from a cached claim -- a permission grant can change
    between two requests from the same still-valid token.
    """

    id: str
    email: str | None
    token: str
    claims: dict[str, Any]


class SupabaseAuth:
    """Verifies Supabase-issued access tokens and delegates permission
    checks back to Supabase's own `can()` function.

    `http_client` is injectable so tests can substitute a transport that
    never leaves the process (see `app/tests/test_api_auth.py`) instead of
    calling a real Supabase project.
    """

    def __init__(
        self,
        *,
        project_url: str,
        anon_key: str,
        audience: str = "authenticated",
        http_client: httpx.Client | None = None,
    ) -> None:
        if not project_url or not anon_key:
            raise AuthError(
                "Supabase is not configured (VISION_SUPABASE_URL / "
                "VISION_SUPABASE_ANON_KEY) -- refusing to verify tokens against nothing."
            )
        self._project_url = project_url.rstrip("/")
        self._anon_key = anon_key
        self._audience = audience
        self._http_client = http_client or httpx.Client(timeout=10.0)
        self._jwks_client = jwt.PyJWKClient(
            f"{self._project_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
        )

    def verify_token(self, token: str) -> AuthenticatedUser:
        """Verify `token`'s signature and expiry against Supabase's JWKS.

        Raises `AuthError` for any failure (expired, malformed, wrong
        signature, wrong audience, unknown key) -- callers should treat
        every failure mode identically (401), not try to distinguish them
        for the caller's benefit.
        """
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self._audience,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"Invalid or expired token: {exc}") from exc

        return AuthenticatedUser(
            id=claims["sub"],
            email=claims.get("email"),
            token=token,
            claims=claims,
        )

    def check_permission(self, user: AuthenticatedUser, permission: str) -> bool:
        """Ask Supabase's `can(_perm)` function whether `user` holds
        `permission`, using `user`'s own token so Postgres evaluates it as
        that user (RLS/`auth.uid()`), not as this backend."""
        response = self._http_client.post(
            f"{self._project_url}/rest/v1/rpc/can",
            json={"_perm": permission},
            headers={
                "Authorization": f"Bearer {user.token}",
                "apikey": self._anon_key,
                "Content-Type": "application/json",
            },
        )
        if response.status_code != 200:
            raise AuthError(
                f"Permission check for {permission!r} failed: "
                f"{response.status_code} {response.text}"
            )
        result = response.json()
        if not isinstance(result, bool):
            raise AuthError(f"Unexpected response from can({permission!r}): {result!r}")
        return result
