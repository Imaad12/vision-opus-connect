"""Unauthenticated liveness/readiness check -- deliberately the only
route in this API that requires neither a session nor a bearer token, so
it can be used as a deploy/monitoring probe. Render's own
`healthCheckPath` (render.yaml) polls this before cutting live traffic
over to a new deploy.

Also checks the connected PostgreSQL database is actually at this
code's own Alembic migration head (see `app.database.schema_check`'s
own docstring for the real production incident this exists to catch --
a deploy going "Live" on code that queries a column/table a migration
was supposed to add, while that migration silently never ran). A
schema that's behind reports 503 here, so a deploy shipped ahead of its
own migration fails Render's health check and traffic stays on the
last good instance instead of going live and 500ing on every request
that touches the new schema. A no-op check (always "ok") for SQLite --
see `schema_check`'s own docstring for why.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.database.schema_check import is_schema_current
from app.database.session import get_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health(response: Response) -> dict[str, str]:
    current, actual, expected = is_schema_current(get_engine())
    if not current:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "schema_behind",
            "database_revision": actual or "unknown",
            "expected_revision": expected or "unknown",
        }
    return {"status": "ok"}
