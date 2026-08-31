"""Application settings.

A single place to resolve configuration (database location, and the API
layer's identity/permission provider) from environment variables, with a
sensible default for local development. Nothing else in the codebase
should read `os.environ` directly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def normalize_postgres_url(url: str) -> str:
    """Ensure a PostgreSQL SQLAlchemy URL names the psycopg (v3) driver
    explicitly (`postgresql+psycopg://`) instead of relying on
    SQLAlchemy's dialect default for a bare `postgresql://` scheme --
    that default is psycopg2, a package this project deliberately does
    not depend on (see pyproject.toml: `psycopg[binary]`, psycopg v3).
    A hosting provider's connection string (e.g. Render's
    VISION_DATABASE_URL) commonly omits the driver suffix entirely,
    which otherwise fails at engine-creation time with
    `ModuleNotFoundError: No module named 'psycopg2'` the first time any
    route actually opens a connection -- not at import time, so nothing
    catches it before a request 500s.

    A URL that already names a driver (`postgresql+psycopg://`,
    `postgresql+asyncpg://`, ...) is returned unchanged, and so is any
    non-PostgreSQL URL (sqlite, ...).
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", env_file=".env", extra="ignore")

    database_path: Path = PROJECT_ROOT / "vision_contracting.db"

    #: A full SQLAlchemy connection string (e.g.
    #: "postgresql+psycopg://user:pass@host:5432/dbname") for production
    #: use, read from VISION_DATABASE_URL. Empty by default, in which case
    #: `resolved_database_url` below falls back to the local SQLite file
    #: at `database_path` -- local development and the test suite are
    #: completely unaffected by this setting existing. Whatever connection
    #: string your hosting provider gives you for its managed Postgres
    #: instance goes here, verbatim.
    database_url: str = ""

    #: Identity/RBAC currently lives in the existing Supabase project the
    #: VINCO frontend already authenticates against (see API_ARCHITECTURE.md
    #: -- this backend deliberately does not duplicate the role/permission
    #: model). Empty by default so the API layer fails closed, loudly, if
    #: these are never configured, rather than silently trusting nothing.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_audience: str = "authenticated"

    #: Browser origins allowed to call this API cross-origin (the frontend
    #: dev server and, in production, the deployed web app's real domain).
    #: Comma-separated in the environment, e.g.
    #: VISION_CORS_ALLOWED_ORIGINS="https://app.example.com,https://staging.example.com".
    #: Defaults cover Vite's common local ports so a fresh checkout works
    #: without any configuration -- without this, every cross-origin
    #: request from the frontend fails browser CORS preflight (a 405 on
    #: OPTIONS, no Access-Control-Allow-Origin header at all), which
    #: surfaces to the user as a generic "Failed to fetch" with no
    #: indication of why.
    cors_allowed_origins: str = (
        "http://localhost:8080,http://127.0.0.1:8080,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def resolved_database_url(self) -> str:
        """The connection string the application actually uses: the
        explicit `database_url` override if set (production), otherwise
        the local SQLite file (development/tests). Normalized so every
        caller (the app engine, Alembic) consistently gets the psycopg
        v3 driver on a PostgreSQL URL, regardless of whether the raw
        VISION_DATABASE_URL value named a driver at all."""
        return normalize_postgres_url(self.database_url or f"sqlite:///{self.database_path}")

    @property
    def is_postgres(self) -> bool:
        return self.resolved_database_url.startswith("postgresql")

    #: Python `logging` level name for the FastAPI process's stdout logs
    #: (see app/core/logging_config.py). "INFO" by default; set
    #: VISION_LOG_LEVEL=WARNING or similar in production to quiet routine
    #: per-request access logs.
    log_level: str = "INFO"

    #: If set, every connection this process makes explicitly runs
    #: `SET search_path TO <staging_schema>` immediately after connecting
    #: (see app/database/schema_isolation.py) -- used only by the staging
    #: verification tooling (app/database/run_staging_verification.py) to
    #: pin every operation inside one isolated PostgreSQL schema, never
    #: touching `public`. Empty by default, in which case nothing about
    #: normal application behavior changes.
    staging_schema: str = ""


settings = Settings()
