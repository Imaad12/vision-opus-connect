"""Shared FastAPI dependencies: DB session, identity, and permissions.

`get_supabase_auth` and `get_current_user` are ordinary FastAPI
dependencies specifically so tests can override them with
`app.dependency_overrides[...]` -- see `app/tests/test_api_clients.py` --
rather than needing a real Supabase project or a real network call.
"""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedUser, AuthError, SupabaseAdmin, SupabaseAuth
from app.api.permission_cache import get_cached_permission, set_cached_permission
from app.api.timing import timed
from app.core.config import settings
from app.database.session import session_scope
from app.models import Company
from app.services.project_service import get_or_create_default_company

__all__ = [
    "get_db",
    "get_supabase_auth",
    "get_supabase_admin",
    "get_current_user",
    "get_current_company",
    "require_permission",
]


def get_db() -> Generator[Session, None, None]:
    """A request-scoped session: commits if the route completes without
    raising, rolls back otherwise -- identical transaction semantics to
    the desktop UI's `session_scope()`, so service-layer code behaves the
    same regardless of which caller it's invoked from."""
    with session_scope() as session:
        yield session


@lru_cache(maxsize=1)
def get_supabase_auth() -> SupabaseAuth:
    """Process-wide `SupabaseAuth` instance. Cached because it holds an
    `httpx.Client` (connection pool) and a JWKS cache that should persist
    across requests, not be rebuilt per call."""
    return SupabaseAuth(
        project_url=settings.supabase_url,
        anon_key=settings.supabase_anon_key,
        audience=settings.supabase_jwt_audience,
    )


@lru_cache(maxsize=1)
def get_supabase_admin() -> SupabaseAdmin:
    """Process-wide `SupabaseAdmin` instance -- see that class's own
    docstring (app/api/auth.py) for the narrow, deliberate reason this
    backend holds a service-role key at all. Only ever depended on by
    `app/api/routers/users.py`'s routes, each already gated behind
    `require_permission("admin.users")`/`"admin.roles"` before this
    dependency is even resolved."""
    return SupabaseAdmin(
        project_url=settings.supabase_url,
        service_role_key=settings.supabase_service_role_key,
    )


def get_current_user(
    authorization: str | None = Header(default=None),
    auth: SupabaseAuth = Depends(get_supabase_auth),
) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        with timed("auth"):
            return auth.verify_token(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_company(session: Session = Depends(get_db)) -> Company:
    """This is still a single-company system (see
    `project_service.get_or_create_default_company`) -- every request
    resolves the one `Company` row. When multi-company support is added,
    this is the one place that changes to resolve company scope from the
    caller instead."""
    return get_or_create_default_company(session)


def require_permission(permission: str):
    """Build a FastAPI dependency that 403s unless `user` holds
    `permission`, per Supabase's `can()` (see `app/api/auth.py`).

    A single, narrow function so every route declares its permission
    requirement the same way `role_permissions` already names it in the
    frontend -- copy the exact string from `app_permission`, don't invent
    a parallel vocabulary (see the frontend permission-string bug fixed
    separately in `purchase-orders.tsx`/`approvals.tsx`).

    A short-TTL cache (app/api/permission_cache.py -- read that module's
    docstring before touching this) is checked first; only a miss/expiry
    reaches Supabase for real. The authorization decision itself is
    still always Supabase's own `can()` -- this only avoids re-asking
    the identical (user, permission) question within a bounded window.
    """

    def _dependency(
        user: AuthenticatedUser = Depends(get_current_user),
        auth: SupabaseAuth = Depends(get_supabase_auth),
    ) -> AuthenticatedUser:
        allowed = get_cached_permission(user.id, permission)
        if allowed is None:
            try:
                with timed("rbac"):
                    allowed = auth.check_permission(user, permission)
            except AuthError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
                ) from exc
            set_cached_permission(user.id, permission, allowed)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return user

    return _dependency
