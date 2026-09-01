"""Purchase Order -> Quotation reference matching (PO ingestion foundation).

A standalone module (mirrors `app.services.import_matching`'s own
separation from `import_service.py`) so it can be imported both by the
staging pipeline (`app.services.import_service.run_po_extraction`, to
compute a match preview immediately at extraction time) and by the
confirmation step (`app.services.client_award_evidence_service`) without either
of those two importing each other.

Matching is exact, whitespace-normalized string comparison only — never
fuzzy/similarity-based. See `app.core.enums.ClientAwardEvidenceMatchStatus` and
PO_ARCHITECTURE.md for the full rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ClientAwardEvidenceMatchStatus
from app.core.import_normalization import normalize_whitespace
from app.models import Quotation

__all__ = ["MatchOutcome", "match_quotation_for_reference"]


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """Result of resolving a PO's extracted reference number against
    existing quotations — see `match_quotation_for_reference`."""

    status: ClientAwardEvidenceMatchStatus
    quotation: Quotation | None = None
    candidate_quotation_ids: list[int] = field(default_factory=list)


def match_quotation_for_reference(session: Session, po_reference_number: str | None) -> MatchOutcome:
    """Resolve `po_reference_number` to an existing `Quotation` by exact,
    whitespace-normalized string comparison only — never a substring or
    fuzzy match, since a reference number is an identifier, not free text
    (same discipline as `suggest_quotation_matches` in
    `app.services.import_matching`).

    Comparison is done in Python against every non-deleted quotation's
    already-normalized reference number, rather than a raw SQL `==`,
    because `Quotation.reference_number` is stored as extracted (OCR/typed
    text) and can legitimately differ from another row only by
    incidental whitespace — exactly the same normalization already
    applied to every other extracted reference field in this codebase
    (`normalize_whitespace`), not a new fuzzy-matching heuristic. This is
    also what makes case D ("PO reference matches multiple quotations")
    representable at all despite `Quotation.reference_number`'s database
    unique constraint on the raw string.

    Returns `UNMATCHED` for an empty/missing reference, `AMBIGUOUS` if
    more than one quotation normalizes to the same reference, `MATCHED`
    for exactly one. Never guesses between candidates.
    """
    normalized = normalize_whitespace(po_reference_number)
    if not normalized:
        return MatchOutcome(status=ClientAwardEvidenceMatchStatus.UNMATCHED)

    stmt = select(Quotation).where(Quotation.is_deleted.is_(False), Quotation.reference_number.is_not(None))
    quotations = session.execute(stmt).scalars().all()
    matches = [q for q in quotations if normalize_whitespace(q.reference_number) == normalized]

    if not matches:
        return MatchOutcome(status=ClientAwardEvidenceMatchStatus.UNMATCHED)
    if len(matches) > 1:
        return MatchOutcome(
            status=ClientAwardEvidenceMatchStatus.AMBIGUOUS,
            candidate_quotation_ids=[q.id for q in matches],
        )
    return MatchOutcome(status=ClientAwardEvidenceMatchStatus.MATCHED, quotation=matches[0])
