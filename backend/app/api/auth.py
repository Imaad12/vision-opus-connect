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
    logic.

UPDATE (native VINCO user management): this backend now *does* hold a
service-role key -- a deliberate, narrow exception, confined entirely to
`SupabaseAdmin` below and only ever invoked from
`app/services/user_service.py`'s admin-user-management functions, never
from `verify_token`/`check_permission`. Creating a Supabase Auth
identity, resetting a password, or (de)activating an account are
admin-level operations no anon-key/user-token request can ever perform,
by Supabase's own design -- there is no way to build a "create other
users" feature on top of Supabase Auth without a service-role key
somewhere, and server-side, behind a permission-gated endpoint, is the
correct and Supabase-documented place for it (never the frontend -- see
`API_ARCHITECTURE.md`). RBAC enforcement itself is completely
unchanged: `require_permission`/`can()` still decide every authorization
question exactly as before.

See API_ARCHITECTURE.md for the full rationale and the migration path
away from Supabase once VINCO has its own identity store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import jwt

__all__ = ["AuthenticatedUser", "AuthError", "SupabaseAuth", "SupabaseAdmin"]

#: Supabase's own convention for an effectively-permanent ban (there is
#: no dedicated "disabled forever" value in the Admin API -- a very long
#: duration is the documented way to express it). ~100 years.
_PERMANENT_BAN_DURATION = "876000h"


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


class SupabaseAdminError(Exception):
    """Raised when a `SupabaseAdmin` operation fails -- a distinct
    exception from `AuthError` (which callers map to 401) since these
    are always either a genuine server-side failure (500) or a caller
    mistake the route maps to a specific 4xx (e.g. duplicate username,
    unknown role) -- never "who are you" or "are you allowed", both of
    which `require_permission` has already settled before any
    `SupabaseAdmin` method is ever called."""


class SupabaseAdmin:
    """Admin-level Supabase operations, authenticated with the
    service-role key -- see this module's docstring for why this class
    exists and the narrow boundary around it. Used only by
    `app/services/user_service.py`.

    Never logs a password or the service-role key itself (only status
    codes / response bodies on failure, and Supabase's own admin API
    never echoes the password back in a response body).
    """

    def __init__(
        self,
        *,
        project_url: str,
        service_role_key: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not project_url or not service_role_key:
            raise SupabaseAdminError(
                "Supabase admin operations are not configured (VISION_SUPABASE_URL / "
                "VISION_SUPABASE_SERVICE_ROLE_KEY) -- refusing to attempt a user-management "
                "operation with no way to authenticate it."
            )
        self._project_url = project_url.rstrip("/")
        self._service_role_key = service_role_key
        self._http_client = http_client or httpx.Client(timeout=10.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._service_role_key}",
            "apikey": self._service_role_key,
            "Content-Type": "application/json",
        }

    def create_auth_user(self, *, email: str, password: str, full_name: str) -> str:
        """Creates a real Supabase Auth identity. `email_confirm: true`
        skips Supabase's normal email-verification flow entirely --
        correct here since this is an internal-only synthetic address
        (`<username>@vinco.local`, never a real inbox anyone can read a
        confirmation link from) and the account is already vetted by
        whichever admin is creating it through VINCO's own UI.

        This also fires Supabase's existing `handle_new_user()` trigger,
        which auto-creates a `profiles` row and a default `user_roles`/
        `user_scopes` row (`employee`/`assigned`, unless this happens to
        be the very first user ever, in which case `super_admin`/`all`)
        -- `set_user_role` below corrects that to the actually-requested
        role right after, for every case except when the default already
        happens to match.

        Returns the new user's id (a UUID).
        """
        response = self._http_client.post(
            f"{self._project_url}/auth/v1/admin/users",
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"full_name": full_name},
            },
            headers=self._headers(),
        )
        if response.status_code not in (200, 201):
            raise SupabaseAdminError(
                f"Failed to create Supabase Auth user: {response.status_code} {response.text}"
            )
        body = response.json()
        user_id = body.get("id")
        if not isinstance(user_id, str):
            raise SupabaseAdminError(f"Unexpected response creating Supabase Auth user: {body!r}")
        return user_id

    def set_password(self, user_id: str, password: str) -> None:
        response = self._http_client.put(
            f"{self._project_url}/auth/v1/admin/users/{user_id}",
            json={"password": password},
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise SupabaseAdminError(
                f"Failed to reset password for {user_id}: {response.status_code} {response.text}"
            )

    def set_banned(self, user_id: str, *, banned: bool) -> None:
        """The active/inactive toggle: Supabase Auth's own account-level
        ban, which `verify_token`/`signInWithPassword` both already
        respect -- a banned user's login attempt and any already-issued
        token both fail at Supabase's own layer, before this backend or
        `can()` ever sees a request from them. Not a `vinco.app_users`-
        only flag that this backend would have to remember to check
        everywhere."""
        response = self._http_client.put(
            f"{self._project_url}/auth/v1/admin/users/{user_id}",
            json={"ban_duration": _PERMANENT_BAN_DURATION if banned else "none"},
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise SupabaseAdminError(
                f"Failed to set banned={banned} for {user_id}: {response.status_code} {response.text}"
            )

    def set_user_role(self, user_id: str, role: str) -> None:
        """Replaces every `public.user_roles` row for `user_id` with
        exactly one row for `role` (VINCO's simplified model gives each
        native user exactly one role, unlike Supabase's own schema which
        technically allows several). Also corrects `public.user_scopes`
        to match -- `all` for `super_admin`, `assigned` otherwise, the
        same convention `handle_new_user()`'s trigger already uses.

        Raises `SupabaseAdminError` (not silently succeeding) if `role`
        isn't a value the `app_role` Postgres enum actually has --
        e.g. `super_user`, until the one-time migration SQL
        (`scripts/native_auth_rbac.sql`) that adds it has been run.
        """
        delete_response = self._http_client.delete(
            f"{self._project_url}/rest/v1/user_roles",
            params={"user_id": f"eq.{user_id}"},
            headers=self._headers(),
        )
        if delete_response.status_code not in (200, 204):
            raise SupabaseAdminError(
                f"Failed to clear existing roles for {user_id}: "
                f"{delete_response.status_code} {delete_response.text}"
            )

        insert_response = self._http_client.post(
            f"{self._project_url}/rest/v1/user_roles",
            json={"user_id": user_id, "role": role},
            headers=self._headers(),
        )
        if insert_response.status_code not in (200, 201):
            raise SupabaseAdminError(
                f"Failed to assign role {role!r} to {user_id} -- if this is a role that "
                "doesn't exist yet in the app_role Postgres enum (e.g. 'super_user'), the "
                "one-time migration SQL must be run first. "
                f"({insert_response.status_code} {insert_response.text})"
            )

        scope = "all" if role == "super_admin" else "assigned"
        scope_response = self._http_client.post(
            f"{self._project_url}/rest/v1/user_scopes",
            json={"user_id": user_id, "scope": scope},
            headers={**self._headers(), "Prefer": "resolution=merge-duplicates"},
        )
        if scope_response.status_code not in (200, 201):
            raise SupabaseAdminError(
                f"Failed to set scope for {user_id}: {scope_response.status_code} {scope_response.text}"
            )
