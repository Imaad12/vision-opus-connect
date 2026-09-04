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
Reverted for that reason -- see this repository's own incident history
for the actual production fix (applying the pending Alembic migration
through Render's Shell), which does not depend on this route at all.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
