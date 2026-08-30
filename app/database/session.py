"""Engine and session management.

This is the only module that knows the database URL. Everything else gets
a `Session` from `session_scope()`.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.database.schema_isolation import pin_search_path_from_settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite doesn't enforce foreign keys unless told to, per connection --
    this PRAGMA is SQLite-specific syntax and meaningless (would error) on
    any other database. PostgreSQL always enforces foreign keys natively,
    so it needs no equivalent -- see `_attach_dialect_listeners`."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _attach_dialect_listeners(engine: Engine) -> None:
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)


def get_engine(database_url: str | None = None) -> Engine:
    """Return the process-wide engine, creating it on first use.

    Passing an explicit `database_url` (e.g. `sqlite:///:memory:` in tests)
    creates a fresh, independent engine rather than reusing the cached one.
    """
    global _engine, _SessionFactory
    if database_url is not None:
        engine = create_engine(database_url, future=True)
        _attach_dialect_listeners(engine)
        pin_search_path_from_settings(engine)
        return engine

    if _engine is None:
        _engine = create_engine(settings.resolved_database_url, future=True)
        _attach_dialect_listeners(_engine)
        pin_search_path_from_settings(_engine)
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional session: commits on success, rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
