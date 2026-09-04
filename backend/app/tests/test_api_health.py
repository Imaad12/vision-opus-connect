"""Tests for `GET /health` -- see `app.database.schema_check`'s own
docstring for the production incident (a deploy live on code that
expected a migration the database never actually got) this route's
schema check exists to catch before Render cuts traffic over to it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import routers
from app.api.main import app


def test_health_reports_ok_against_the_real_sqlite_test_database():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_503_when_the_schema_check_reports_a_mismatch(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        routers.health,
        "is_schema_current",
        lambda engine: (False, "0316ad9e1d33", "7a1c9e2f5b3d"),
    )
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "schema_behind",
        "database_revision": "0316ad9e1d33",
        "expected_revision": "7a1c9e2f5b3d",
    }
