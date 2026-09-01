"""Regression test for the actual Alembic migration chain against a real
PostgreSQL database -- something no other test in this suite does.

Every other test (including test_postgres_compat.py) builds its schema via
`Base.metadata.create_all(engine)`, straight from the current SQLAlchemy
models. That's correct by construction and can never catch a bug in the
*migration files themselves* -- which is exactly how five real
Postgres-incompatible migrations (raw integer `server_default`s on
Boolean columns, e.g. `server_default=sa.text('1')`, valid SQLite DDL but
rejected by Postgres as a DatatypeMismatch) went undetected: reproduced
directly against a real, disposable Postgres database, tracing a
"Customers module fails to load" report back to this exact class of bug.

This also guards the two-step deploy procedure
`migrations/versions/926e160784a0_postgresql_baseline_schema.py`'s own
docstring documents as required for a *fresh* PostgreSQL database
(`alembic stamp cb86207a716e` before `alembic upgrade head`, not a plain
`alembic upgrade head` from scratch) -- a real, easy-to-miss step; if a
deployment ever ran the chain "the obvious way" instead, migrations would
abort partway (confirmed: DuplicateTable on `clients`, since the squash
migration recreates tables the 14 migrations before it already made).

Runs the real `alembic` CLI as a subprocess (not Alembic's Python API --
that shares this test process's own cached DB engine/connection pool in
a way that deadlocked against this module's own schema-reset step) so
each step is an independent, short-lived connection, exactly like a real
deployment running these same commands from a shell.

Skipped entirely unless `VISION_TEST_POSTGRES_URL` is set to a disposable
PostgreSQL database (same convention as test_postgres_compat.py) -- this
test drops and recreates a whole schema and would not be safe to run
against a shared or production database.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSTGRES_TEST_URL = os.environ.get("VISION_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="VISION_TEST_POSTGRES_URL not set -- skipping migration-chain tests",
)

# The revision migrations/versions/926e160784a0's own docstring names as
# the point to stamp-without-running before `upgrade head` on a fresh
# PostgreSQL database.
STAMP_BEFORE_SQUASH = "cb86207a716e"
SCHEMA = "vinco"


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["VISION_DATABASE_URL"] = POSTGRES_TEST_URL or ""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _reset_schema() -> None:
    engine = create_engine(POSTGRES_TEST_URL, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
            conn.commit()
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_database() -> None:
    """DROP SCHEMA CASCADE is the only clean reset for a schema built by a
    real migration run (it also owns its own alembic_version table)."""
    _reset_schema()
    yield


def test_documented_stamp_then_upgrade_reaches_head_cleanly() -> None:
    """The procedure migrations/versions/926e160784a0's docstring documents
    for a fresh PostgreSQL database must actually work end-to-end, with no
    error, all the way to head."""
    stamp_result = _run_alembic("stamp", STAMP_BEFORE_SQUASH)
    assert stamp_result.returncode == 0, stamp_result.stderr

    upgrade_result = _run_alembic("upgrade", "head")
    assert upgrade_result.returncode == 0, upgrade_result.stderr

    engine = create_engine(POSTGRES_TEST_URL, future=True)
    try:
        table_names = set(inspect(engine).get_table_names(schema=SCHEMA))
    finally:
        engine.dispose()
    # A representative sample spanning the whole history: clients (from
    # the very first migration), and the two tables whose columns the
    # bug actually broke (actual_costs, estimate_revisions) plus a
    # regular later addition (vendors) -- proving the run didn't just
    # exit early having silently skipped the failing steps.
    for expected in ("clients", "vendors", "actual_costs", "estimate_revisions"):
        assert expected in table_names, f"{expected!r} missing after upgrade to head"


def test_naive_upgrade_head_without_stamp_fails_loudly_on_a_fresh_db() -> None:
    """Documents the actual current failure mode (not a guess) for anyone
    who runs `alembic upgrade head` against a truly fresh PostgreSQL
    database without the stamp step first -- so this stays a known,
    intentional trade-off instead of silently regressing into something
    worse (e.g. succeeding but leaving a half-correct schema)."""
    result = _run_alembic("upgrade", "head")
    assert result.returncode != 0
    assert "clients" in result.stderr
