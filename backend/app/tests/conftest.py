from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.api.permission_cache import clear_permission_cache
from app.database.base import Base
from app.database.session import get_engine


@pytest.fixture(autouse=True)
def _reset_permission_cache() -> Generator[None, None, None]:
    """`require_permission` now caches a permission decision for
    `settings.permission_cache_ttl_seconds` (app/api/permission_cache.py).
    The cache is keyed by (user_id, permission) and lives at module scope
    for the whole test process; several API test files use the same fixed
    test user id ("user-1") across many tests, and some flip a permission
    on/off mid-test (see api_test_support.py's `_SelfInvalidatingSet`,
    which handles that specific case). This autouse fixture is the
    belt-and-braces guarantee that no test ever observes a permission
    decision cached by a DIFFERENT test -- clears before AND after every
    test, regardless of which fake-auth pattern that test uses."""
    clear_permission_cache()
    yield
    clear_permission_cache()


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
