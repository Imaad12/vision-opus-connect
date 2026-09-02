from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.engine import make_url

from alembic import context

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.core.config import settings
from app.database.base import Base
from app.database.schema_isolation import pin_search_path, verify_search_path

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use the application's own settings for the database URL rather than a
# hardcoded value in alembic.ini, so migrations always target the same
# database the application would use.
#
# `set_main_option` stores this into a configparser section, which treats
# '%' as the start of a '%(name)s' interpolation -- a literal '%' in the
# URL (e.g. a percent-encoded password character, or a `?options=...`
# query string like the one a schema-scoped connection string can carry)
# must be escaped as '%%' or configparser raises
# "invalid interpolation syntax" before the URL is ever used.
config.set_main_option("sqlalchemy.url", settings.resolved_database_url.replace("%", "%%"))

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    # `render_as_batch` is a SQLite-only workaround (it can't ALTER TABLE
    # natively, so Alembic recreates the whole table instead) -- forcing
    # it on for PostgreSQL would work but pointlessly rebuild whole tables
    # for changes Postgres can apply directly, so it's dialect-conditional.
    is_sqlite = make_url(url).get_backend_name() == "sqlite"
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=is_sqlite,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # A `-c search_path=...` startup option is only honored if whatever
    # sits between this process and the real backend forwards it --
    # confirmed that Supabase's Supavisor Session Pooler silently drops
    # it, and that a stock PgBouncer instead hard-rejects the connection
    # outright for carrying an option it doesn't recognize. Neither
    # problem exists for `SET search_path` sent as a normal query after
    # connecting, so VISION_STAGING_SCHEMA (never the connection string
    # itself) is how the intended schema travels to this process; pin it
    # and verify it actually took before running any migration DDL.
    #
    # `staging_schema` defaults to "vinco" for every environment,
    # SQLite included (see Settings.staging_schema / test_config.py) --
    # `CREATE SCHEMA`/`SET search_path` are PostgreSQL-only syntax, so
    # this must stay dialect-gated the same way
    # `pin_search_path_from_settings` (the app's own runtime engine
    # path) already is, or a bare `alembic upgrade head` against a
    # fresh SQLite database -- exactly what a new checkout's README
    # documents -- fails outright with `OperationalError: near
    # "SCHEMA": syntax error` before a single migration runs. Confirmed
    # this was a real, live bug, not a hypothetical: reproduced against
    # a genuinely fresh SQLite file before adding this guard.
    if settings.staging_schema and connectable.dialect.name == "postgresql":
        pin_search_path(connectable, settings.staging_schema)
        actual_schema = verify_search_path(connectable, settings.staging_schema)
        if actual_schema != settings.staging_schema:
            raise RuntimeError(
                f"Schema isolation failed: expected current_schema() = "
                f"'{settings.staging_schema}' but got '{actual_schema}' even after an "
                "explicit SET search_path. Refusing to run migrations -- DDL would not "
                "land where intended."
            )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
