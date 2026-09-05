"""Runs `alembic upgrade head` before this container's web process starts
accepting traffic -- see `backend/Dockerfile`'s `CMD`, which runs this
module and only `exec`s uvicorn if it exits 0.

Why this exists: a deploy went "Live" on Render (commit eae6ae9) with
code that queries `import_batches.notes` -- a column added by migration
`7a1c9e2f5b3d` -- while the connected PostgreSQL database was still on
the previous revision, because `render.yaml`'s `preDeployCommand:
"alembic upgrade head"` never actually ran for this deploy. That field
only takes effect automatically for a service Render manages as a
synced Blueprint (created via "New +" -> "Blueprint"); this Render
service predates this repository and was only ever repointed to it via
Settings -> Build & Deploy, which does not make it Blueprint-managed --
see `render.yaml`'s own comment on `preDeployCommand` for the full
history, including that this is the SECOND time this exact incident
class has happened. Fixing the Render dashboard setting (or converting
to a Blueprint) would also fix it, but requires Shell/dashboard access
this project's operator does not have. Baking the migration into the
container's own startup command instead works unconditionally: it is
just what `docker run` (or however Render invokes this image) executes
before the process is considered started at all, independent of
Blueprint sync, plan tier, or Shell availability.

Deliberately NOT invoked from `app/worker.py`. `render.yaml`'s worker
service points its own `dockerCommand` directly at `python -m
app.worker`, which never imports or calls anything in this module --
only the web service's Dockerfile `CMD` (this module, then `exec
uvicorn`) ever runs a migration, exactly once per deploy, matching
`render.yaml`'s own "exactly one process ever runs `alembic upgrade
head` per deploy" comment on the worker block.

Runs `alembic upgrade head` as a real subprocess, not Alembic's Python
API (`alembic.command.upgrade`) -- deliberately: `app/tests/
test_migrations.py`'s own docstring documents a real deadlock hit when
a process already holding a database connection/pool called Alembic's
Python API against the same database. A subprocess has its own
completely independent connection, unaffected by whatever this process
holds open for the advisory lock below.

For PostgreSQL, the upgrade is wrapped in a session-scoped
`pg_advisory_lock` held on a single dedicated connection (own engine,
`NullPool` -- never `app.database.session.get_engine()`'s pooled
singleton, which this module has no reason to touch at all) so that if
Render ever starts more than one instance of this service around the
same deploy, only one actually runs the migration; the other blocks on
the lock, then finds the database already at head and Alembic's own
upgrade is a safe no-op. The lock is always released, even if the
migration itself fails. A no-op for every other dialect (SQLite, used
in local dev/tests) -- there is no advisory-lock concept there, and none
is needed: local dev/tests are always single-process.

Never logs the database URL or any credential -- only alembic's own
stdout/stderr (migration file names, revision ids), which never include
the connection string.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.pool import NullPool

from app.core.config import PROJECT_ROOT, settings

_logger = logging.getLogger("app.database.migrate")

#: Arbitrary, fixed 64-bit signed integer used as this deployment's one
#: PostgreSQL advisory lock key -- any two processes calling
#: `pg_advisory_lock` with the SAME key serialize against each other,
#: regardless of the key's actual meaning. Never change this value: a
#: migration already in flight under the old key while a new deploy uses
#: a different one would defeat the whole point of the lock.
_MIGRATION_LOCK_KEY = 8_412_663_501_927_001


def _is_postgres(url: str) -> bool:
    return make_url(url).get_backend_name() == "postgresql"


def _run_alembic_upgrade() -> None:
    """Runs `python -m alembic upgrade head` as a subprocess, explicitly
    passing this process's own resolved `VISION_DATABASE_URL` through
    `env=` rather than relying on inheriting `os.environ` unchanged --
    the child must migrate the exact same database this process resolved
    to, even if that value came from something other than a literal
    environment variable (a test monkeypatching `settings.database_url`
    directly, for instance)."""
    env = dict(os.environ)
    env["VISION_DATABASE_URL"] = settings.database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        _logger.error("alembic upgrade head failed (exit %s):\n%s", result.returncode, output)
        raise RuntimeError(f"alembic upgrade head exited with status {result.returncode}")
    if output.strip():
        _logger.info(output)


def _run_with_advisory_lock(url: str) -> None:
    lock_engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        with lock_engine.connect() as connection:
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            _logger.info("Acquiring migration advisory lock...")
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
            try:
                _logger.info("Lock acquired -- running alembic upgrade head")
                _run_alembic_upgrade()
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _MIGRATION_LOCK_KEY})
    finally:
        lock_engine.dispose()


def run_migrations() -> None:
    """The one entry point this module exists for: bring the resolved
    database to this checkout's Alembic head. Raises on any failure --
    the caller (`main` below) is what turns that into a non-zero process
    exit, which is what makes `backend/Dockerfile`'s `CMD` refuse to
    `exec uvicorn` afterward."""
    url = settings.resolved_database_url
    if not _is_postgres(url):
        _run_alembic_upgrade()
        return
    _run_with_advisory_lock(url)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _logger.info("Running database migrations...")
    try:
        run_migrations()
    except Exception:
        _logger.exception("Database migration failed -- refusing to start the application")
        return 1
    _logger.info("Migration complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
