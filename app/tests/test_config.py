"""Tests for `app.core.config.normalize_postgres_url` and
`Settings.resolved_database_url`.

Regression coverage for a real production incident: Render's
VISION_DATABASE_URL was a bare `postgresql://...` connection string
(no driver suffix), which SQLAlchemy resolves to psycopg2 by default --
a package this project doesn't install (it depends on psycopg v3). That
failed at engine-creation time, inside the first request that actually
opened a connection, as `ModuleNotFoundError: No module named
'psycopg2'`, surfacing to callers as a bare 500 with no earlier signal.
"""

from __future__ import annotations

from app.core.config import Settings, normalize_postgres_url


def test_bare_postgresql_url_gets_psycopg_driver() -> None:
    assert (
        normalize_postgres_url("postgresql://user:pass@host:5432/dbname")
        == "postgresql+psycopg://user:pass@host:5432/dbname"
    )


def test_already_prefixed_psycopg_url_is_unchanged() -> None:
    url = "postgresql+psycopg://user:pass@host:5432/dbname"
    assert normalize_postgres_url(url) == url


def test_other_postgres_driver_prefix_is_left_alone() -> None:
    # Not this project's driver, but normalize_postgres_url must not
    # clobber an explicit, deliberate driver choice.
    url = "postgresql+asyncpg://user:pass@host:5432/dbname"
    assert normalize_postgres_url(url) == url


def test_sqlite_url_is_unchanged() -> None:
    assert normalize_postgres_url("sqlite:///some/path.db") == "sqlite:///some/path.db"


def test_settings_resolved_database_url_normalizes_bare_postgres_url() -> None:
    settings = Settings(database_url="postgresql://user:pass@host:5432/dbname")
    assert settings.resolved_database_url == "postgresql+psycopg://user:pass@host:5432/dbname"


def test_settings_resolved_database_url_falls_back_to_sqlite_when_unset() -> None:
    settings = Settings(database_url="")
    assert settings.resolved_database_url.startswith("sqlite:///")
