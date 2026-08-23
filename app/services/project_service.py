"""Project-related business logic.

This is intentionally minimal in Phase 1 — just enough for the UI shell to
prove that presentation code goes through a service rather than talking to
SQLAlchemy directly. CRUD and richer project operations belong here in
later phases.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project


def count_active_projects(session: Session) -> int:
    """Number of projects that have not been soft-deleted."""
    stmt = select(func.count()).select_from(Project).where(Project.is_deleted.is_(False))
    return session.execute(stmt).scalar_one()
