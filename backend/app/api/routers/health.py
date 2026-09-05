"""Unauthenticated liveness check -- deliberately the only route in this
API that requires neither a session nor a bearer token, so it can be used
as a deploy/monitoring probe.

Deliberately does NOT touch the database. A prior version (commit
ad1a0b9) added a PostgreSQL Alembic-head comparison here to catch a
deploy shipping ahead of its own migration -- intended as a safety net,
but Render polls `healthCheckPath` frequently and treats a failing
health check as an ongoing liveness failure, not just a one-time
deploy-cutover gate; with the schema genuinely behind (the exact
condition it was designed to detect), that turned into repeated
503s on a running instance and a multi-minute-feeling site, which is a
far worse outcome than the silent-500 case it was meant to prevent.
Reverted for that reason. The actual production fix for a schema
lagging behind the code that queries it is `app.database.
migrate_production` (run from `backend/Dockerfile`'s own `CMD`, before
`exec uvicorn` -- see that module's own docstring), which happens once
per container start, not on every poll of this route.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
