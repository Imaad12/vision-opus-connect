"""Shared test doubles/fixture helpers for `app/tests/test_api_*.py`.

Not a test module itself (no `test_` prefix, so pytest won't collect it)
-- just the boilerplate every API test file needs: an in-memory database
usable across Starlette's TestClient worker thread, and a fake Supabase
permission-check double so tests never need a real Supabase project.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.database.session as db_session_module
from app.api.auth import AuthenticatedUser
from app.api.deps import get_current_user, get_db, get_supabase_auth
from app.api.main import create_app
from app.api.permission_cache import clear_permission_cache
from app.database.base import Base

__all__ = ["FakeSupabaseAuth", "make_memory_engine", "make_api_client"]


class _SelfInvalidatingSet(set):
    """A `set` that clears `app.api.permission_cache`'s cache on any
    mutation. `require_permission` now caches a permission decision for
    `settings.permission_cache_ttl_seconds` (see that module) -- every
    caller in this test file uses the fixed test user `id="user-1"`
    (`make_api_client` below), so without this, a test that does
    `api_client.granted.discard("x.create")` expecting the very next
    request to see the permission as revoked would instead get a stale
    cached "allowed" from before the discard. Real Supabase-backed
    production behavior is unaffected: this class only ever wraps the
    fake test double's `granted` set, never anything reachable outside
    tests."""

    def add(self, *args, **kwargs):
        clear_permission_cache()
        return super().add(*args, **kwargs)

    def discard(self, *args, **kwargs):
        clear_permission_cache()
        return super().discard(*args, **kwargs)

    def remove(self, *args, **kwargs):
        clear_permission_cache()
        return super().remove(*args, **kwargs)

    def clear(self, *args, **kwargs):
        clear_permission_cache()
        return super().clear(*args, **kwargs)


class FakeSupabaseAuth:
    """Grants exactly the permissions a test configures, and never makes a
    network call -- `check_permission` is the only method the API layer
    calls on it after `get_current_user` has already run."""

    def __init__(self, granted: set[str]) -> None:
        self.granted = _SelfInvalidatingSet(granted)

    def check_permission(self, _user: AuthenticatedUser, permission: str) -> bool:
        return permission in self.granted


def make_memory_engine() -> Engine:
    # `check_same_thread=False` + `StaticPool` (one connection, reused) --
    # required because Starlette's TestClient runs synchronous route
    # handlers in a worker thread, and a bare `sqlite:///:memory:`
    # database is otherwise a fresh, empty, thread-local database per
    # connection (see SQLAlchemy's SQLite in-memory testing docs).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return engine


def make_api_client(engine: Engine, granted: set[str]) -> Generator[TestClient, None, None]:
    """Yields a `TestClient` wired to `engine` with a controllable fake
    permission set (mutate the returned client's `.granted` set mid-test
    to flip a permission on/off)."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    auth = FakeSupabaseAuth(granted)

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
        id="user-1", email="tester@example.com", token="fake-token", claims={}
    )
    app.dependency_overrides[get_supabase_auth] = lambda: auth

    # `app.database.session.session_scope()` is a plain module-level
    # function, not something `app.dependency_overrides` can touch at
    # all -- it's what a FastAPI *background task* uses (see
    # app/api/routers/imports.py's upload-then-background-process
    # split), since that code runs after the request (and its
    # `Depends(get_db)`) has already finished, with no request context
    # to inject a dependency into. Left alone, it lazily builds a REAL
    # engine from `settings.resolved_database_url` the first time
    # anything calls it -- in this sandbox, an already-set
    # VISION_DATABASE_URL pointing at a real Supabase Postgres instance,
    # which a background-task test discovered the hard way (a real
    # connection attempt that hung against this environment's network
    # policy instead of failing fast). Monkeypatching the SAME
    # engine/factory this fixture already built for `get_db` into that
    # module's globals makes any code calling `session_scope()` during
    # this test -- present or future, in this router or another --
    # transparently use the identical in-memory test database, with no
    # possibility of ever reaching a real one regardless of what's set
    # in the environment.
    original_engine = db_session_module._engine
    original_factory = db_session_module._SessionFactory
    db_session_module._engine = engine
    db_session_module._SessionFactory = factory
    try:
        with TestClient(app) as client:
            client.granted = auth.granted  # type: ignore[attr-defined]
            yield client
    finally:
        db_session_module._engine = original_engine
        db_session_module._SessionFactory = original_factory
