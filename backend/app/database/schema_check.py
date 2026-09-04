"""Is the connected PostgreSQL database actually at the Alembic revision
this running code's migration chain expects?

Exists because of a real production incident: a deploy went "Live" on
Render at commit eae6ae9 with code (app/api/routers/imports.py's
`_batch_read`) that selects `import_batches.notes` -- a column added by
migration 7a1c9e2f5b3d -- while the connected PostgreSQL database was
still at the previous revision, because the Render service's
Pre-Deploy Command never actually ran `alembic upgrade head` for this
deploy (render.yaml declares `preDeployCommand: "alembic upgrade
head"`, but Render only auto-runs a render.yaml Pre-Deploy Command for
a service it manages as a synced Blueprint; this service was created
long before this repository existed and only had its connected GitHub
repository swapped in the dashboard's Settings -> Build & Deploy tab --
see render.yaml's own top comment -- which does not turn it into a
Blueprint-managed service). The result: every `POST /imports/batches`
request 500'd with `psycopg.errors.UndefinedColumn`, indistinguishable
at Render's `/health` check from a fully healthy deploy, because
`/health` never touched the database at all.

`is_schema_current` is the readiness check that closes that gap -- see
`app.api.routers.health` for where it's actually wired to
`GET /health`, which is what Render's own `healthCheckPath` polls
before cutting live traffic over to a new instance.

Deliberately a no-op (always "current") for SQLite: this codebase's own
tests build their schema via `Base.metadata.create_all` (see
app/tests/conftest.py), never by running Alembic migrations against the
in-memory test database, so a SQLite database genuinely has no
`alembic_version` table to compare against and that is not a problem to
report -- Alembic is the schema source of truth for PostgreSQL
(production) only.
"""

from __future__ import annotations

import logging

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from app.core.config import PROJECT_ROOT

_logger = logging.getLogger("app.database")

_MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def get_expected_head() -> str | None:
    """The single Alembic revision this checkout's migration chain
    resolves to -- what a PostgreSQL database should be stamped at once
    every migration file in `migrations/versions` has been applied."""
    return ScriptDirectory(str(_MIGRATIONS_DIR)).get_current_head()


def get_database_revision(engine: Engine) -> str | None:
    """The revision PostgreSQL's own `alembic_version` table currently
    records, or None if that table doesn't exist yet (a database that
    has never had a migration applied against it at all)."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def is_schema_current(engine: Engine) -> tuple[bool, str | None, str | None]:
    """Returns `(is_current, database_revision, expected_head)`.

    Always reports current (`True, None, None`) for a non-PostgreSQL
    engine -- see this module's own docstring on why SQLite is exempt.

    Never raises: a failure to even determine the schema state (the
    connection itself is down, `alembic_version` genuinely has no row)
    is reported as NOT current with both revisions as None, so a
    caller like the `/health` route fails safe -- loud and visible --
    rather than crashing or, worse, reporting "ok" while unable to
    actually verify that.
    """
    if engine.dialect.name != "postgresql":
        return True, None, None
    try:
        expected = get_expected_head()
        actual = get_database_revision(engine)
    except Exception:
        _logger.exception("Could not determine Alembic schema state")
        return False, None, None
    return actual == expected, actual, expected
