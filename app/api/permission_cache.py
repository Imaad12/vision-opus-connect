"""Short-TTL, in-process cache for Supabase RBAC permission-check results.

## Why this exists
`SupabaseAuth.check_permission()` (app/api/auth.py) makes a real HTTPS
round trip to Supabase's PostgREST `can()` RPC on every call. The
performance audit confirmed this is the single largest per-request
backend latency contributor on every permission-gated endpoint (34
routers use `require_permission`). A user loading one page commonly
fires several requests in quick succession -- e.g. a dashboard pulling
customers, projects, and quotations within well under a second -- and
distinct requests for the SAME (user, permission) pair (a page reload,
navigating back to a list, a background refetch) re-ask the identical
question every time with zero reuse.

## What this does NOT change
The authorization MODEL is untouched: still Supabase's own `can()`
function, evaluated against the caller's own token, still the single
source of truth for who can do what. This only shortens how often that
source of truth gets asked the exact same question, for a bounded
window -- it never grants a permission Supabase itself wouldn't have,
and every miss/expiry falls through to a real check exactly as before.

## TTL
Default 15 seconds (`VISION_PERMISSION_CACHE_TTL_SECONDS`). Chosen to
cover one page's request burst (typically well under 2 seconds) without
holding a decision anywhere close to as long as an admin action
(assigning/revoking a role, editing role_permissions) would realistically
need to matter for an internal business application. Set to 0 (or a
negative value) to disable entirely -- every call then always falls
through to a real Supabase check, identical to pre-cache behavior.

## Revocation behavior
A permission revoked (or granted) via Supabase's dashboard/SQL takes UP
TO `ttl_seconds` to be reflected in this process's decisions for a user
who already holds a cached entry for that exact (user_id, permission)
pair. Both allow AND deny are cached symmetrically for the same TTL, so
a newly-granted permission becomes visible within the same bound as a
revoked one -- no asymmetric "revocation lags grants" surprise. There is
no external invalidation channel (no admin action busts a specific
user's cache) -- deliberate: bounding the TTL short enough that this
doesn't matter in practice was judged safer than adding an invalidation
path (a webhook/pubsub) whose own failure mode -- a bust that never
arrives -- would silently produce a WORSE staleness window than the
bounded one it replaces.

## Multi-user isolation
Cache key is `(user_id, permission)`. `user_id` is `AuthenticatedUser.id`
-- set only after `SupabaseAuth.verify_token` has already verified the
caller's JWT signature -- never a header or any client-supplied value a
caller could forge to read another user's cached entry. Two different
users' entries never collide by construction.

## Process behavior
A plain in-process dict guarded by a `threading.Lock` (FastAPI runs sync
dependencies -- `require_permission`'s dependency function is sync -- in
a thread-pool executor, so concurrent requests genuinely run on
different OS threads, not just interleaved coroutines; the lock makes
each get/set atomic rather than relying on CPython dict-op atomicity
alone). Cleared on every process restart/deploy. NOT shared across
multiple worker processes or Render instances -- this codebase's
Dockerfile currently runs a single `uvicorn` process with no `--workers`
flag, so that's a non-issue today. If that ever changes, each
process/instance keeps its own independent cache: still correctly
bounded by the same TTL, just uncoordinated, meaning up to (worker
count) redundant real checks can happen instead of one -- never an
incorrect or unsafe decision either way.

## Security implications
The only thing this cache changes for an attacker who already holds a
valid, currently-permitted token: that permitted decision can be reused
for up to `ttl_seconds` even if revoked in the interim. This is the same
risk class as the JWT's own expiry window or a DNS TTL already accepted
elsewhere in this system -- bounded, observable (a fixed constant, never
attacker-influenced), and never grants access beyond what a real check
would have returned at cache-write time. JWT verification itself
(`SupabaseAuth.verify_token`) is NOT cached here and still runs on every
single request.
"""

from __future__ import annotations

import time
from threading import Lock

from app.core.config import settings

_cache: dict[tuple[str, str], tuple[bool, float]] = {}
_lock = Lock()


def get_cached_permission(user_id: str, permission: str) -> bool | None:
    """Returns the cached decision if present and unexpired, else None
    (meaning: no cached answer, the caller must ask Supabase for real)."""
    if settings.permission_cache_ttl_seconds <= 0:
        return None
    with _lock:
        entry = _cache.get((user_id, permission))
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() >= expires_at:
        return None
    return value


def set_cached_permission(user_id: str, permission: str, value: bool) -> None:
    if settings.permission_cache_ttl_seconds <= 0:
        return
    expires_at = time.monotonic() + settings.permission_cache_ttl_seconds
    with _lock:
        _cache[(user_id, permission)] = (value, expires_at)


def clear_permission_cache() -> None:
    """Test-only: drop every cached entry regardless of TTL."""
    with _lock:
        _cache.clear()
