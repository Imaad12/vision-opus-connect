"""Tests for `app.database.schema_check` -- the Alembic-head-vs-database
readiness guard added after a real production incident: a deploy went
"Live" on Render at commit eae6ae9 with code that queries
`import_batches.notes` (added by migration 7a1c9e2f5b3d) while the
connected PostgreSQL database was still on the previous revision,
because the Render service's Pre-Deploy Command never actually ran
`alembic upgrade head` for that deploy. `GET /health` (test_api_health.py)
is the route that actually uses this; these tests cover the check
itself in isolation.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from app.database import schema_check
from app.database.session import get_engine


def test_get_expected_head_resolves_the_real_migration_chain():
    # A canary, not a tautology: if this ever changes, it means a new
    # migration was added and this literal needs a one-line update --
    # exactly the kind of drift this module exists to catch on the
    # database side, made visible here on the code side too.
    assert schema_check.get_expected_head() == "7a1c9e2f5b3d"


class TestIsSchemaCurrent:
    def test_sqlite_is_always_reported_current(self):
        # This project's own tests build their schema via
        # `Base.metadata.create_all` (app/tests/conftest.py), never by
        # running Alembic against the in-memory test database, so a
        # SQLite engine genuinely has no `alembic_version` table --
        # Alembic is the schema source of truth for PostgreSQL only.
        engine = get_engine("sqlite:///:memory:")
        is_current, actual, expected = schema_check.is_schema_current(engine)
        assert is_current is True
        assert actual is None
        assert expected is None

    def test_postgres_at_the_expected_head_is_current(self, monkeypatch: pytest.MonkeyPatch):
        fake_engine = _fake_postgres_engine()
        monkeypatch.setattr(schema_check, "get_database_revision", lambda engine: "7a1c9e2f5b3d")
        is_current, actual, expected = schema_check.is_schema_current(fake_engine)
        assert is_current is True
        assert actual == "7a1c9e2f5b3d"
        assert expected == "7a1c9e2f5b3d"

    def test_postgres_behind_the_expected_head_is_not_current(self, monkeypatch: pytest.MonkeyPatch):
        # The exact shape of the real incident: the database is still
        # stamped at the migration before the one that added the
        # columns the running code now expects.
        fake_engine = _fake_postgres_engine()
        monkeypatch.setattr(schema_check, "get_database_revision", lambda engine: "0316ad9e1d33")
        is_current, actual, expected = schema_check.is_schema_current(fake_engine)
        assert is_current is False
        assert actual == "0316ad9e1d33"
        assert expected == "7a1c9e2f5b3d"

    def test_a_failure_to_determine_the_revision_reports_not_current_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        fake_engine = _fake_postgres_engine()

        def _raise(engine: Engine) -> str | None:
            raise RuntimeError("connection refused")

        monkeypatch.setattr(schema_check, "get_database_revision", _raise)
        is_current, actual, expected = schema_check.is_schema_current(fake_engine)
        assert is_current is False
        assert actual is None
        assert expected is None


class _FakeDialect:
    name = "postgresql"


class _FakeEngine:
    dialect = _FakeDialect()


def _fake_postgres_engine() -> Engine:
    # A real Engine is unnecessary here -- `is_schema_current` only ever
    # reads `.dialect.name` off it directly; `get_database_revision`
    # (the thing that would actually open a connection) is monkeypatched
    # in every test that reaches it.
    return _FakeEngine()  # type: ignore[return-value]
