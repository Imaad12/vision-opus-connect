from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.database.base import Base
from app.database.session import get_engine


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
