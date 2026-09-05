"""Tests for `app.database.migrate_production` -- the module
`backend/Dockerfile`'s `CMD` now runs before `exec`-ing uvicorn, so a
deploy can never go "Live" with a schema behind its own code again (see
that module's own docstring for the production incident this fixes).

The SQLite-path tests below run for real, unconditionally: they migrate
an actual temporary SQLite file through the real Alembic chain via a
real subprocess, then inspect the resulting file -- not a mock of any
part of this. The PostgreSQL-specific tests (the advisory lock actually
serializing concurrent callers) are skipped unless `VISION_TEST_POSTGRES_URL`
is set, exactly like `test_postgres_compat.py`/`test_migrations.py` --
this sandbox has no real PostgreSQL and no network path to one, so
these are verified for real by CI's `postgres-integration` job
(`.github/workflows/backend-ci.yml`), never by a mock standing in for
what a real advisory lock does.
"""

from __future__ import annotations

import inspect
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect

from app.core.config import PROJECT_ROOT, settings
from app.database import migrate_production

POSTGRES_TEST_URL = os.environ.get("VISION_TEST_POSTGRES_URL")


class TestIsPostgres:
    def test_recognizes_a_postgres_url(self):
        assert migrate_production._is_postgres("postgresql+psycopg://user:pass@host/db") is True

    def test_recognizes_a_sqlite_url_as_not_postgres(self):
        assert migrate_production._is_postgres("sqlite:////tmp/x.db") is False


class TestRunMigrationsSqlite:
    """Real subprocess, real Alembic chain, real temporary SQLite file --
    the exact code path this module uses in production when the resolved
    database isn't PostgreSQL, and the one every local dev/test
    environment actually exercises."""

    def test_migrates_a_fresh_sqlite_database_to_head(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")

        migrate_production.run_migrations()

        assert db_path.exists()
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        tables = set(sa_inspect(engine).get_table_names())
        engine.dispose()
        # Spot-checks spanning the whole migration chain, not just the
        # latest revision -- proves this actually ran every migration
        # from scratch, not just the newest one against an already-built
        # schema.
        assert "import_batches" in tables
        assert "import_jobs" in tables  # added by 7a1c9e2f5b3d -- the head this whole fix is about
        assert "clients" in tables

    def test_running_it_twice_against_an_already_current_database_is_a_safe_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        db_path = tmp_path / "twice.db"
        monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")

        migrate_production.run_migrations()
        migrate_production.run_migrations()  # must not raise, must not duplicate anything

        engine = create_engine(f"sqlite:///{db_path}", future=True)
        assert "import_jobs" in set(sa_inspect(engine).get_table_names())
        engine.dispose()

    def test_a_failed_upgrade_raises_and_never_reports_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # An unwritable target directory makes `alembic upgrade head`
        # fail for a real, external reason (not a mock standing in for
        # "pretend this failed") -- proves a genuine failure propagates
        # as an exception rather than being swallowed.
        unwritable_dir = tmp_path / "unwritable"
        unwritable_dir.mkdir(mode=0o500)
        db_path = unwritable_dir / "sub" / "cant-create-this.db"
        monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")

        with pytest.raises(RuntimeError, match="alembic upgrade head exited"):
            migrate_production.run_migrations()


class TestMain:
    def test_returns_zero_and_migrates_on_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        db_path = tmp_path / "main-ok.db"
        monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")

        assert migrate_production.main() == 0
        assert db_path.exists()

    def test_returns_one_and_does_not_raise_on_failure(self, monkeypatch: pytest.MonkeyPatch):
        def _boom() -> None:
            raise RuntimeError("simulated migration failure")

        monkeypatch.setattr(migrate_production, "run_migrations", _boom)

        assert migrate_production.main() == 1  # never raises out of main() -- this IS the process exit code


class TestDockerfileWiring:
    def test_the_web_services_cmd_runs_migrations_before_exec_ing_uvicorn(self):
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
        assert "app.database.migrate_production" in dockerfile
        assert "&& exec uvicorn" in dockerfile

    def test_the_worker_service_does_not_run_migrations(self):
        render_yaml = (PROJECT_ROOT / "render.yaml").read_text()
        # Crude but effective and exact: the worker's own dockerCommand
        # line must be the plain module invocation, never anything that
        # also runs a migration first -- see render.yaml's own comment on
        # why exactly one process per deploy may ever do that.
        assert 'dockerCommand: "python -m app.worker"' in render_yaml


def _imports(module_source: str, name: str) -> bool:
    """True if `module_source` actually imports `name` (an `import ...`
    or `from ... import` statement) -- not merely mentions its name, e.g.
    in a docstring pointing a reader at it."""
    return any(
        line.strip().startswith(("import ", "from ")) and name in line
        for line in module_source.splitlines()
    )


class TestNeverCalledFromHealthOrWorker:
    def test_the_health_route_does_not_import_migrate_production(self):
        import app.api.routers.health as health_module

        assert not _imports(inspect.getsource(health_module), "migrate_production")

    def test_the_worker_module_does_not_import_migrate_production(self):
        import app.worker as worker_module

        assert not _imports(inspect.getsource(worker_module), "migrate_production")


@pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="VISION_TEST_POSTGRES_URL not set -- skipping PostgreSQL advisory-lock tests",
)
class TestAdvisoryLockAgainstRealPostgres:
    """Runs for real in CI's postgres-integration job
    (.github/workflows/backend-ci.yml), against a real, disposable
    postgres:16 service container -- not runnable in this sandbox (no
    network path to any PostgreSQL instance), so this class is the part
    of P12 ("advisory lock acquisition/release") this sandbox cannot
    itself verify. See this session's final report for that honestly
    stated rather than assumed."""

    def test_migrating_the_same_database_twice_sequentially_succeeds(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "database_url", POSTGRES_TEST_URL)
        migrate_production.run_migrations()
        migrate_production.run_migrations()  # second call: lock acquired again, finds head already reached

    def test_two_concurrent_callers_against_the_same_database_both_succeed_without_racing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Resets to a schema Alembic hasn't touched yet, then fires two
        # `run_migrations()` calls at effectively the same moment on
        # separate threads -- `subprocess.run` releases the GIL for the
        # long-running alembic child process, so this is a genuine race
        # on the real database, not a scripted-safe interleaving. Without
        # the advisory lock, this is exactly the shape of race that would
        # let two `alembic upgrade head` invocations attempt the same
        # `CREATE TABLE` concurrently.
        monkeypatch.setattr(settings, "database_url", POSTGRES_TEST_URL)
        engine = create_engine(POSTGRES_TEST_URL, future=True)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA IF EXISTS vinco CASCADE")
        engine.dispose()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(migrate_production.run_migrations) for _ in range(2)]
            for future in futures:
                future.result()  # re-raises if either call failed

        engine = create_engine(POSTGRES_TEST_URL, future=True)
        with engine.connect() as connection:
            connection.exec_driver_sql("SET search_path TO vinco")
            tables = set(sa_inspect(connection).get_table_names(schema="vinco"))
        engine.dispose()
        assert "import_jobs" in tables
