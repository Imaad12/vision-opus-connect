"""Unauthenticated liveness check -- deliberately the only route in this
API that requires neither a session nor a bearer token, so it can be used
as a deploy/monitoring probe."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
