"""Project/client/quotation match suggestions for the import review screen.

Deterministic, heuristic matching only (substring/equality on project
number, project name, client name, and exact quotation reference number)
— no fuzzy-matching library and no AI. Suggestions are exactly that: the
user always explicitly chooses "Use Existing", "Create New", or "Review
Manually" (see IMPORT_ARCHITECTURE.md §9); nothing here ever merges a
document into an existing project/client/quotation on its own.

`suggest_quotation_matches` is advisory only — it surfaces what already
exists so a reviewer has the information to decide; the actual
conflict-blocking logic (an incoming revision dated earlier than, or
tied with a differing total to, the matched quotation's current version)
lives in `app.services.import_service.confirm_import`, the one place
that's allowed to write to the `Quotation`/`QuotationVersion` tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Client, ImportedQuotationCandidate, Project, Quotation
from app.services.quotation_service import get_current_version

_MAX_SUGGESTIONS = 5


@dataclass(frozen=True, slots=True)
class QuotationMatch:
    """One existing `Quotation` that shares a candidate's reference number,
    plus enough of its current version's data for a reviewer to compare
    against the incoming document without leaving the review screen."""

    quotation: Quotation
    current_version_date: date | None
    current_version_total: Decimal | None

    @property
    def reference_number(self) -> str | None:
        return self.quotation.reference_number

    @property
    def project_name(self) -> str | None:
        return self.quotation.project.name if self.quotation.project else None

    @property
    def client_name(self) -> str | None:
        project = self.quotation.project
        return project.client.name if project and project.client else None


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


def suggest_quotation_matches(session: Session, candidate: ImportedQuotationCandidate) -> list[QuotationMatch]:
    """Existing quotations whose reference number exactly matches this
    candidate's extracted `quotation_number` — never a substring or fuzzy
    match, since a reference number is an identifier, not free text.

    `Quotation.reference_number` carries a database-wide unique
    constraint, so this can only ever return zero or one match today —
    it's still returned as a list, both for symmetry with
    `suggest_project_matches`/`suggest_client_matches` and so a reviewer
    always sees a structured, iterable result rather than special-casing
    "one vs. none."
    """
    reference = (candidate.quotation_number or "").strip()
    if not reference:
        return []

    stmt = (
        select(Quotation)
        .options(joinedload(Quotation.project).joinedload(Project.client))
        .where(Quotation.is_deleted.is_(False), Quotation.reference_number == reference)
        .limit(_MAX_SUGGESTIONS)
    )
    quotations = session.execute(stmt).unique().scalars().all()

    matches = []
    for quotation in quotations:
        current_version = get_current_version(session, quotation)
        matches.append(
            QuotationMatch(
                quotation=quotation,
                current_version_date=current_version.issued_date if current_version else None,
                current_version_total=current_version.quoted_value if current_version else None,
            )
        )
    return matches
