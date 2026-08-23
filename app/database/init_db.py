"""Create a fresh SQLite database from the current models.

This is for local development and tests only. An existing database with
real data must go through Alembic migrations (see `migrations/`) instead,
so that schema changes are reviewed and never destructive.
"""

from __future__ import annotations

from sqlalchemy import Engine

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.database.base import Base
from app.database.session import get_engine


def create_all(engine: Engine | None = None) -> Engine:
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    return engine


if __name__ == "__main__":
    create_all()
    print("Database created.")
