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

from sqlalchemy import create_engine

from app.core.config import Settings, normalize_postgres_url
from app.database.schema_isolation import pin_search_path_from_settings


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


def test_staging_schema_defaults_to_vinco() -> None:
    # This is what keeps VINCO's own tables out of Supabase's `public`
    # schema by default -- see app/core/config.py's field docstring for
    # the full rationale (public already owns Auth/RBAC tables plus
    # pre-existing UUID-keyed application tables that collide by name
    # with several of VINCO's own).
    assert Settings().staging_schema == "vinco"


def test_cors_allowed_origins_list_always_includes_desktop_origins_even_when_env_overridden() -> None:
    # Render's VISION_CORS_ALLOWED_ORIGINS fully replaces the default
    # string (Settings only reads it, never appends to it) -- so if
    # whoever configured it only listed the web app's own https:// domain
    # (the natural thing to do, since `tauri://localhost` isn't a domain
    # anyone would think to add there), the desktop build would be
    # silently CORS-blocked. cors_allowed_origins_list must union the
    # desktop origins in regardless of what the env var says.
    settings = Settings(cors_allowed_origins="https://app.example.com")
    origins = settings.cors_allowed_origins_list
    assert "https://app.example.com" in origins
    assert "tauri://localhost" in origins
    assert "https://tauri.localhost" in origins


def test_cors_allowed_origins_list_does_not_duplicate_desktop_origin_if_already_configured() -> None:
    settings = Settings(cors_allowed_origins="https://app.example.com,tauri://localhost")
    assert settings.cors_allowed_origins_list.count("tauri://localhost") == 1


def test_pin_search_path_from_settings_is_a_no_op_for_sqlite(monkeypatch) -> None:
    # SET search_path / CREATE SCHEMA are PostgreSQL-only syntax; against
    # a SQLite engine they must never even be attempted, since
    # staging_schema now defaults to "vinco" for every environment,
    # local SQLite dev included.
    import app.core.config as config_module

    monkeypatch.setattr(config_module.settings, "staging_schema", "vinco")
    engine = create_engine("sqlite:///:memory:", future=True)
    pin_search_path_from_settings(engine)  # must not raise
    with engine.connect() as conn:
        from sqlalchemy import text

        assert conn.execute(text("SELECT 1")).scalar_one() == 1
