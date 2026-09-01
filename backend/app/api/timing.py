"""Per-request phase timing: how much of a request's total time went to
auth (JWT verification), RBAC (Supabase `can()` check), and database
round trips, so a slow endpoint can be diagnosed from production logs
without guessing.

Contextvar-based (not a `request.state` field threaded through every
dependency signature) so `get_current_user`/`require_permission`/the
DB-event listeners don't need a `Request` parameter added just to record
a number -- each async request gets its own context automatically via
Python's contextvars + asyncio task-local propagation, and nothing here
holds a reference across requests, so there's no cross-request leakage
even under concurrent requests in the same process.

`record()` is a no-op if no request is currently being timed (e.g. in a
unit test that calls a service function directly, or a script that
imports this module without going through the middleware) -- always
safe to call unconditionally from any code path.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_timing: ContextVar[dict[str, float] | None] = ContextVar("_timing", default=None)


def start_request_timing() -> None:
    """Called once per request, at the very start (by AccessLogMiddleware)."""
    _timing.set({})


def record(phase: str, seconds: float) -> None:
    """Add `seconds` to the running total for `phase` in the current
    request's timing dict. Accumulates rather than overwrites, since a
    phase (most likely "db") can legitimately fire more than once per
    request."""
    bucket = _timing.get()
    if bucket is None:
        return
    bucket[phase] = bucket.get(phase, 0.0) + seconds


@contextmanager
def timed(phase: str) -> Iterator[None]:
    start = time.monotonic()
    try:
        yield
    finally:
        record(phase, time.monotonic() - start)


def get_request_timing() -> dict[str, float]:
    """Read the current request's accumulated phase timings (empty dict
    if no phases were recorded, e.g. an unauthenticated 401 that never
    reached a DB call)."""
    return dict(_timing.get() or {})
