"""Project/client match suggestions for the import review screen.

Deterministic, heuristic matching only (substring/equality on project
number, project name, and client name) — no fuzzy-matching library and no
AI. Suggestions are exactly that: the user always explicitly chooses
"Use Existing", "Create New", or "Review Manually" (see
IMPORT_ARCHITECTURE.md §9); nothing here ever merges a document into an
existing project/client on its own.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Client, ImportedQuotationCandidate, Project

_MAX_SUGGESTIONS = 5


def suggest_project_matches(session: Session, candidate: ImportedQuotationCandidate) -> list[Project]:
    conditions = []
    if candidate.project_number:
        conditions.append(Project.project_code.ilike(candidate.project_number))
    if candidate.project_name:
        conditions.append(Project.name.ilike(f"%{candidate.project_name}%"))
    if not conditions:
        return []

    stmt = (
        select(Project)
        .options(joinedload(Project.client))
        .where(Project.is_deleted.is_(False))
        .where(or_(*conditions))
        .order_by(Project.created_at.desc())
        .limit(_MAX_SUGGESTIONS)
    )
    return list(session.execute(stmt).unique().scalars().all())


def suggest_client_matches(session: Session, candidate: ImportedQuotationCandidate) -> list[Client]:
    if not candidate.client_name:
        return []

    stmt = (
        select(Client)
        .where(Client.is_deleted.is_(False))
        .where(Client.name.ilike(f"%{candidate.client_name}%"))
        .order_by(Client.name)
        .limit(_MAX_SUGGESTIONS)
    )
    return list(session.execute(stmt).scalars().all())
