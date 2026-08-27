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

from app.api.auth import AuthenticatedUser
from app.api.deps import get_current_user, get_db, get_supabase_auth
from app.api.main import create_app
from app.database.base import Base

__all__ = ["FakeSupabaseAuth", "make_memory_engine", "make_api_client"]


class FakeSupabaseAuth:
    """Grants exactly the permissions a test configures, and never makes a
    network call -- `check_permission` is the only method the API layer
    calls on it after `get_current_user` has already run."""

    def __init__(self, granted: set[str]) -> None:
        self.granted = granted

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

    with TestClient(app) as client:
        client.granted = auth.granted  # type: ignore[attr-defined]
        yield client
