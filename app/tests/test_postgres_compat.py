"""PostgreSQL dialect-compatibility tests.

These exercise the handful of things that are genuinely dialect-sensitive
in the schema (partial unique indexes, boolean server defaults, foreign
key enforcement) against a *real* PostgreSQL database, since SQLite's
dialect quirks (integer-backed booleans, no native ALTER TABLE) can hide
bugs that only surface on Postgres -- see `app/models/cost.py` and
`migrations/versions/926e160784a0_postgresql_baseline_schema.py`.

Skipped entirely unless `VISION_TEST_POSTGRES_URL` is set to a disposable
PostgreSQL database (never a shared or production one -- this test suite
creates and drops all tables). Not run by default / in normal CI:

    VISION_TEST_POSTGRES_URL="postgresql+psycopg://user:pass@host/db" \\
        pytest app/tests/test_postgres_compat.py
"""

from __future__ import annotations

import os
from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.core.enums import DEFAULT_CURRENCY
from app.database.base import Base
from app.database.session import get_engine
from app.models.client import Client
from app.models.company import Company
from app.models.cost import ActualCost, EstimateRevision
from app.models.lookups import CostCategory
from app.models.project import Project

POSTGRES_TEST_URL = os.environ.get("VISION_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="VISION_TEST_POSTGRES_URL not set -- skipping PostgreSQL-specific compatibility tests",
)


@pytest.fixture
def pg_engine() -> Generator[Engine, None, None]:
    engine = get_engine(POSTGRES_TEST_URL)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def pg_session(pg_engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _make_project(session: Session) -> Project:
    company = Company(name="Test Co", default_currency=DEFAULT_CURRENCY)
    client = Client(name="Test Client")
    session.add_all([company, client])
    session.flush()
    project = Project(
        company_id=company.id,
        client_id=client.id,
        name="Test Project",
        status="LEAD",
        contract_currency=DEFAULT_CURRENCY,
    )
    session.add(project)
    session.flush()
    return project


def test_boolean_server_defaults_apply_on_insert(pg_session: Session) -> None:
    """`is_final`/`is_tax_recoverable` use `false()`/`true()` server defaults
    (app/models/cost.py) instead of a raw `text("0")`/`text("1")` precisely
    because the latter renders as an integer literal, which fails on
    Postgres's real boolean type -- this proves the fix actually works
    end-to-end against a real Postgres server."""
    project = _make_project(pg_session)
    category = CostCategory(name="Materials")
    pg_session.add(category)
    pg_session.flush()

    revision = EstimateRevision(project_id=project.id, revision_number=1)
    cost = ActualCost(project_id=project.id, cost_category_id=category.id, amount=Decimal("100.00"))
    pg_session.add_all([revision, cost])
    pg_session.commit()

    pg_session.refresh(revision)
    pg_session.refresh(cost)
    assert revision.is_final is False
    assert cost.is_tax_recoverable is True


def test_partial_unique_index_allows_many_non_final_revisions(pg_session: Session) -> None:
    project = _make_project(pg_session)
    pg_session.add_all(
        [
            EstimateRevision(project_id=project.id, revision_number=1, is_final=False),
            EstimateRevision(project_id=project.id, revision_number=2, is_final=False),
            EstimateRevision(project_id=project.id, revision_number=3, is_final=False),
        ]
    )
    pg_session.commit()  # would raise IntegrityError if the index were a plain unique index


def test_partial_unique_index_rejects_second_final_revision(pg_session: Session) -> None:
    """The partial index (`postgresql_where=text("is_final = true")`) must
    actually be honored on Postgres -- if the `postgresql_where` kwarg were
    ever dropped, this would silently become a plain unique index and this
    test would still pass for the wrong reason, so
    `test_partial_unique_index_allows_many_non_final_revisions` above is
    the half of this pair that would actually catch that regression."""
    project = _make_project(pg_session)
    pg_session.add(EstimateRevision(project_id=project.id, revision_number=1, is_final=True))
    pg_session.commit()

    pg_session.add(EstimateRevision(project_id=project.id, revision_number=2, is_final=True))
    with pytest.raises(IntegrityError):
        pg_session.commit()


def test_foreign_keys_enforced(pg_session: Session) -> None:
    cost = ActualCost(project_id=999999, cost_category_id=999999, amount=Decimal("1.00"))
    pg_session.add(cost)
    with pytest.raises(IntegrityError):
        pg_session.commit()
