"""Force every connection made through an Engine onto one PostgreSQL
schema via an explicit `SET search_path`, rather than relying on the
connection string's `-c search_path=...` startup option or embedding
that option in the connection string at all.

Two things, both confirmed by direct testing against real poolers, rule
out the startup-option approach entirely:

- Supabase's Supavisor Session Pooler silently drops the option, leaving
  new connections on `current_schema() = 'public'` regardless of what
  the connection string asked for.
- A stock PgBouncer instance instead hard-rejects the connection outright
  ("unsupported startup parameter in options: search_path") -- so simply
  embedding the option "just in case a pooler happens to honor it" is
  actively unsafe, not merely ineffective, against at least one common
  real pooler.

`SET search_path` sent as a normal SQL statement after the connection is
already established has neither failure mode -- no pooler has a reason
to inspect or reject an ordinary query. The schema name itself travels
between this process and any subprocess it starts (Alembic, pytest,
uvicorn) via the `VISION_STAGING_SCHEMA` environment variable / the
`Settings.staging_schema` field, never via the connection string.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine


def pin_search_path(engine: Engine, schema: str) -> None:
    """Register a `connect` listener on `engine` that runs
    `SET search_path TO "schema"` as the first statement on every new
    DBAPI connection, before any other code gets a chance to issue DDL
    or DML on it. Idempotent to call twice with the same schema (harmless
    duplicate listener); call once per engine per schema in practice.

    Commits immediately after the SET -- confirmed by direct testing
    (through a real PgBouncer instance) that otherwise, since this fires
    as the very first statement on the connection, it stays inside the
    implicit transaction PostgreSQL opens on that first statement;
    SQLAlchemy's own checkin behavior later issues a ROLLBACK to leave
    the pooled connection clean, and PostgreSQL documents that a plain
    (non-LOCAL) SET's effect is undone if the transaction that issued it
    is rolled back. Without this commit, the SET would appear to work on
    a connection's first use and silently revert to the session's
    original search_path (typically `public`) on every subsequent
    checkout of the same pooled connection -- exactly the failure this
    function exists to prevent."""

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()
        dbapi_connection.commit()


def pin_search_path_from_settings(engine: Engine) -> None:
    """Convenience for the app's own engine-creation path: pin `engine`
    to `settings.staging_schema` if that's set, otherwise do nothing.
    Always safe to call unconditionally -- a no-op for every normal
    (non-staging) use of this application."""
    from app.core.config import settings

    if settings.staging_schema:
        pin_search_path(engine, settings.staging_schema)


def verify_search_path(engine: Engine, expected_schema: str) -> str | None:
    """Connect once and return the actual `current_schema()`, so a
    caller can assert it matches `expected_schema` before trusting that
    any DDL it's about to run will land in the right place. Returns the
    actual value (which may be None if the search_path resolves to no
    existing schema at all) rather than raising, so callers can produce
    their own contextual error message."""
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(text("SELECT current_schema()")).scalar()
