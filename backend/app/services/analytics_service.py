"""Historical quotation/PO pipeline analytics (read-only query layer).

Every figure here is either a direct read or a sum/count/average over
fields that already exist and are already correct:
`Quotation`/`QuotationVersion`/`Project`/`Client` (quotation and award
data — unchanged, uses `quotation_service.mark_awarded`'s own output,
never a second award computation) and `ClientAwardEvidence`/
`ImportedClientAwardEvidenceCandidate` (PO/matching data). No new arithmetic is
introduced beyond summing/counting/averaging (the same style
`app.services.dashboard_service`/`app.services.financial_service` already
use); `app.core.financial_engine` is not touched or duplicated, since
none of these metrics are profit/margin/cost figures.

See `ANALYTICS_ARCHITECTURE.md` for the precise definition of every
metric below (in particular: which quotation "value" is used, how a
quotation with no value/date is handled, and the difference between
"awarded" and "has a PO"). This module builds no UI and stores nothing —
it is purely a query layer for a future dashboard to call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Final

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.enums import Currency, ImportReviewStatus, ProjectStatus, ClientAwardEvidenceMatchStatus, QuotationStatus
from app.models import (
    ImportedDocument,
    ImportedClientAwardEvidenceCandidate,
    Project,
    ClientAwardEvidence,
    Quotation,
    QuotationVersion,
)

__all__ = [
    "QuotationPipelineSummary",
    "ClientPerformance",
    "ProjectPerformance",
    "PeriodTrend",
    "QuotationToPoTimingSummary",
    "PendingClientAwardEvidenceSummary",
    "PoFinancialAnalysis",
    "CurrencyBreakdown",
    "compute_quotation_pipeline_summary",
    "compute_client_performance",
    "compute_project_performance",
    "compute_monthly_trends",
    "compute_yearly_trends",
    "compute_average_time_to_po",
    "list_quotations_without_po",
    "list_unmatched_client_award_evidence_candidates",
    "compute_pending_client_award_evidence_summary",
    "compute_po_financial_analysis",
    "compute_quotation_currency_breakdown",
    "compute_po_currency_breakdown",
]

ZERO: Final[Decimal] = Decimal("0")


# --- Shared helpers ------------------------------------------------------------


def _current_versions_by_quotation(session: Session, quotation_ids: list[int]) -> dict[int, QuotationVersion]:
    """The current version of every given quotation — same ordering rule
    as `app.services.quotation_service.get_current_version` (most recent
    `issued_date`, nulls last, then highest id), computed in one query
    pass rather than one query per quotation. This is the only place that
    ordering rule is reimplemented outside `quotation_service` itself; it
    must stay in lockstep with it (see that function's own docstring for
    why "current" means dated-most-recently, never inserted-most-recently).
    """
    if not quotation_ids:
        return {}
    stmt = select(QuotationVersion).where(
        QuotationVersion.quotation_id.in_(quotation_ids), QuotationVersion.is_deleted.is_(False)
    )
    versions = session.execute(stmt).scalars().all()

    def sort_key(version: QuotationVersion) -> tuple[bool, date, int]:
        return (version.issued_date is not None, version.issued_date or date.min, version.id)

    current: dict[int, QuotationVersion] = {}
    for version in versions:
        existing = current.get(version.quotation_id)
        if existing is None or sort_key(version) > sort_key(existing):
            current[version.quotation_id] = version
    return current


def _non_deleted_quotations(session: Session, *, with_project_client: bool = False) -> list[Quotation]:
    stmt = select(Quotation).where(Quotation.is_deleted.is_(False))
    if with_project_client:
        stmt = stmt.options(joinedload(Quotation.project).joinedload(Project.client))
    result = session.execute(stmt)
    return list((result.unique() if with_project_client else result).scalars().all())


# --- 1. Quotation pipeline summary ----------------------------------------------


@dataclass(frozen=True, slots=True)
class QuotationPipelineSummary:
    quotation_count: int
    #: Quotations whose current version has no `quoted_value` at all --
    #: excluded from `quoted_value_total`/`average_quotation_value`
    #: (a missing value is a data-completeness gap, not a real zero).
    quotations_missing_value_count: int
    quoted_value_total: Decimal
    average_quotation_value: Decimal | None
    awarded_quotation_count: int
    awarded_value_total: Decimal
    quotations_with_po_count: int
    quotations_without_po_count: int
    #: `quotations_with_po_count / quotation_count`, or `None` if there are
    #: no quotations at all yet. See ANALYTICS_ARCHITECTURE.md for why this
    #: is distinct from "awarded" (a quotation can be awarded manually,
    #: with no ClientAwardEvidence ever recorded).
    quotation_to_po_conversion_rate: Decimal | None


def compute_quotation_pipeline_summary(session: Session) -> QuotationPipelineSummary:
    quotations = _non_deleted_quotations(session)
    quotation_count = len(quotations)
    quotation_ids = [q.id for q in quotations]
    current_versions = _current_versions_by_quotation(session, quotation_ids)

    quoted_values = [v.quoted_value for v in current_versions.values() if v.quoted_value is not None]
    quoted_value_total = sum(quoted_values, ZERO)
    average_quotation_value = (quoted_value_total / len(quoted_values)) if quoted_values else None

    awarded_versions = [v for v in current_versions.values() if v.status == QuotationStatus.WON]
    awarded_quotation_count = len(awarded_versions)

    project_by_quotation_id = {q.id: q.project_id for q in quotations}
    awarded_project_ids = {
        project_by_quotation_id[v.quotation_id]
        for v in awarded_versions
        if v.quotation_id in project_by_quotation_id
    }
    awarded_value_total = ZERO
    if awarded_project_ids:
        projects = session.execute(select(Project).where(Project.id.in_(awarded_project_ids))).scalars().all()
        awarded_value_total = sum((p.contract_value for p in projects if p.contract_value is not None), ZERO)

    with_po_ids: set[int] = set()
    if quotation_ids:
        with_po_ids = set(
            session.execute(
                select(ClientAwardEvidence.quotation_id).where(ClientAwardEvidence.quotation_id.in_(quotation_ids)).distinct()
            )
            .scalars()
            .all()
        )
    quotations_with_po_count = len(with_po_ids)
    quotations_without_po_count = quotation_count - quotations_with_po_count
    conversion_rate = (
        Decimal(quotations_with_po_count) / Decimal(quotation_count) if quotation_count else None
    )

    return QuotationPipelineSummary(
        quotation_count=quotation_count,
        quotations_missing_value_count=quotation_count - len(quoted_values),
        quoted_value_total=quoted_value_total,
        average_quotation_value=average_quotation_value,
        awarded_quotation_count=awarded_quotation_count,
        awarded_value_total=awarded_value_total,
        quotations_with_po_count=quotations_with_po_count,
        quotations_without_po_count=quotations_without_po_count,
        quotation_to_po_conversion_rate=conversion_rate,
    )


# --- 2. Client-wise / project-wise performance ----------------------------------


@dataclass(frozen=True, slots=True)
class ClientPerformance:
    client_id: int
    client_name: str
    quotation_count: int
    quoted_value_total: Decimal
    awarded_count: int
    awarded_value_total: Decimal


def compute_client_performance(session: Session) -> list[ClientPerformance]:
    quotations = _non_deleted_quotations(session, with_project_client=True)
    current_versions = _current_versions_by_quotation(session, [q.id for q in quotations])

    buckets: dict[int, dict] = {}
    for quotation in quotations:
        project = quotation.project
        client = project.client if project else None
        if client is None:
            continue
        bucket = buckets.setdefault(
            client.id, {"name": client.name, "count": 0, "quoted": ZERO, "awarded_count": 0, "awarded": ZERO}
        )
        bucket["count"] += 1
        version = current_versions.get(quotation.id)
        if version is not None and version.quoted_value is not None:
            bucket["quoted"] += version.quoted_value
        if version is not None and version.status == QuotationStatus.WON:
            bucket["awarded_count"] += 1
            if project.contract_value is not None:
                bucket["awarded"] += project.contract_value

    return [
        ClientPerformance(
            client_id=client_id,
            client_name=bucket["name"],
            quotation_count=bucket["count"],
            quoted_value_total=bucket["quoted"],
            awarded_count=bucket["awarded_count"],
            awarded_value_total=bucket["awarded"],
        )
        for client_id, bucket in buckets.items()
    ]


@dataclass(frozen=True, slots=True)
class ProjectPerformance:
    project_id: int
    project_name: str
    client_name: str | None
    status: ProjectStatus
    quotation_count: int
    quoted_value_total: Decimal
    contract_value: Decimal | None


def compute_project_performance(session: Session) -> list[ProjectPerformance]:
    quotations = _non_deleted_quotations(session, with_project_client=True)
    current_versions = _current_versions_by_quotation(session, [q.id for q in quotations])

    buckets: dict[int, dict] = {}
    for quotation in quotations:
        project = quotation.project
        if project is None:
            continue
        bucket = buckets.setdefault(
            project.id,
            {
                "name": project.name,
                "client_name": project.client.name if project.client else None,
                "status": project.status,
                "contract_value": project.contract_value,
                "count": 0,
                "quoted": ZERO,
            },
        )
        bucket["count"] += 1
        version = current_versions.get(quotation.id)
        if version is not None and version.quoted_value is not None:
            bucket["quoted"] += version.quoted_value

    return [
        ProjectPerformance(
            project_id=project_id,
            project_name=bucket["name"],
            client_name=bucket["client_name"],
            status=bucket["status"],
            quotation_count=bucket["count"],
            quoted_value_total=bucket["quoted"],
            contract_value=bucket["contract_value"],
        )
        for project_id, bucket in buckets.items()
    ]


# --- 3. Monthly / yearly trends --------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeriodTrend:
    #: "YYYY-MM" for a monthly trend, "YYYY" for a yearly one.
    period: str
    quotation_count: int
    quoted_value_total: Decimal
    awarded_count: int
    awarded_value_total: Decimal


def _compute_trends(session: Session, *, period_key: Callable[[date], str]) -> list[PeriodTrend]:
    quotations = _non_deleted_quotations(session, with_project_client=True)
    current_versions = _current_versions_by_quotation(session, [q.id for q in quotations])

    buckets: dict[str, dict] = {}
    for quotation in quotations:
        version = current_versions.get(quotation.id)
        # A quotation with no known issued_date cannot be placed on a
        # timeline -- excluded from trends entirely, never guessed at
        # (e.g. from import time, which is not a business date).
        if version is None or version.issued_date is None:
            continue
        key = period_key(version.issued_date)
        bucket = buckets.setdefault(key, {"count": 0, "quoted": ZERO, "awarded_count": 0, "awarded": ZERO})
        bucket["count"] += 1
        if version.quoted_value is not None:
            bucket["quoted"] += version.quoted_value
        if version.status == QuotationStatus.WON:
            bucket["awarded_count"] += 1
            project = quotation.project
            if project is not None and project.contract_value is not None:
                bucket["awarded"] += project.contract_value

    return [
        PeriodTrend(
            period=key,
            quotation_count=bucket["count"],
            quoted_value_total=bucket["quoted"],
            awarded_count=bucket["awarded_count"],
            awarded_value_total=bucket["awarded"],
        )
        for key, bucket in sorted(buckets.items())
    ]


def compute_monthly_trends(session: Session) -> list[PeriodTrend]:
    return _compute_trends(session, period_key=lambda d: f"{d.year:04d}-{d.month:02d}")


def compute_yearly_trends(session: Session) -> list[PeriodTrend]:
    return _compute_trends(session, period_key=lambda d: f"{d.year:04d}")


# --- 4. Quotation -> PO timing ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuotationToPoTimingSummary:
    #: Number of POs actually included in the average -- always report
    #: this alongside `average_days`, since it is frequently a small
    #: fraction of all POs (see field docstring below).
    sample_size: int
    average_days: Decimal | None


def compute_average_time_to_po(session: Session) -> QuotationToPoTimingSummary:
    """Average of (`ClientAwardEvidence.po_date` - the awarded quotation
    version's `issued_date`) in days.

    Deliberately narrow: only a `ClientAwardEvidence` that itself recorded
    `awarded_quotation_version_id` (set only when *that* PO triggered the
    award — see `client_award_evidence_service.confirm_client_award_evidence_import`;
    a later, evidence-only PO against an already-awarded quotation never
    sets it) and where both dates are actually known is included. Never
    backfilled from a different version or estimated when a date is
    missing.
    """
    client_award_evidence = session.execute(select(ClientAwardEvidence).where(ClientAwardEvidence.is_deleted.is_(False))).scalars().all()
    version_ids = {po.awarded_quotation_version_id for po in client_award_evidence if po.awarded_quotation_version_id}
    versions_by_id: dict[int, QuotationVersion] = {}
    if version_ids:
        versions_by_id = {
            v.id: v
            for v in session.execute(select(QuotationVersion).where(QuotationVersion.id.in_(version_ids))).scalars().all()
        }

    deltas: list[int] = []
    for po in client_award_evidence:
        if po.po_date is None or po.awarded_quotation_version_id is None:
            continue
        version = versions_by_id.get(po.awarded_quotation_version_id)
        if version is None or version.issued_date is None:
            continue
        deltas.append((po.po_date - version.issued_date).days)

    if not deltas:
        return QuotationToPoTimingSummary(sample_size=0, average_days=None)
    return QuotationToPoTimingSummary(sample_size=len(deltas), average_days=Decimal(sum(deltas)) / Decimal(len(deltas)))


# --- 5. Quotations with no PO / unmatched POs ------------------------------------


def list_quotations_without_po(session: Session) -> list[Quotation]:
    quotations = _non_deleted_quotations(session)
    if not quotations:
        return []
    quotation_ids = [q.id for q in quotations]
    with_po_ids = set(
        session.execute(select(ClientAwardEvidence.quotation_id).where(ClientAwardEvidence.quotation_id.in_(quotation_ids)).distinct())
        .scalars()
        .all()
    )
    return [q for q in quotations if q.id not in with_po_ids]


def list_unmatched_client_award_evidence_candidates(session: Session) -> list[ImportedClientAwardEvidenceCandidate]:
    """Every currently `UNMATCHED`, not-yet-resolved PO candidate — see
    `client_award_evidence_service.reconcile_unmatched_client_award_evidence`, which is
    what can move one of these to `MATCHED` once its quotation is later
    imported. A `REJECTED`/`CONFIRMED` document is excluded: it has
    already reached a final human decision."""
    stmt = (
        select(ImportedClientAwardEvidenceCandidate)
        .join(ImportedDocument, ImportedClientAwardEvidenceCandidate.imported_document_id == ImportedDocument.id)
        .where(
            ImportedClientAwardEvidenceCandidate.match_status == ClientAwardEvidenceMatchStatus.UNMATCHED,
            ImportedDocument.review_status == ImportReviewStatus.NEEDS_REVIEW,
        )
    )
    return list(session.execute(stmt).scalars().all())


@dataclass(frozen=True, slots=True)
class PendingClientAwardEvidenceSummary:
    unmatched_count: int
    ambiguous_count: int


def compute_pending_client_award_evidence_summary(session: Session) -> PendingClientAwardEvidenceSummary:
    stmt = (
        select(ImportedClientAwardEvidenceCandidate.match_status)
        .join(ImportedDocument, ImportedClientAwardEvidenceCandidate.imported_document_id == ImportedDocument.id)
        .where(ImportedDocument.review_status == ImportReviewStatus.NEEDS_REVIEW)
    )
    statuses = session.execute(stmt).scalars().all()
    return PendingClientAwardEvidenceSummary(
        unmatched_count=sum(1 for s in statuses if s == ClientAwardEvidenceMatchStatus.UNMATCHED),
        ambiguous_count=sum(1 for s in statuses if s == ClientAwardEvidenceMatchStatus.AMBIGUOUS),
    )


# --- 6. PO financial analysis (where data is actually available) ---------------


@dataclass(frozen=True, slots=True)
class PoFinancialAnalysis:
    client_award_evidence_count: int
    #: Each `*_sample_size` may legitimately be smaller than
    #: `client_award_evidence_count` -- not every real PO document carries a
    #: readable net/tax/gross figure (see PO_ARCHITECTURE.md's known
    #: table-reading-order limitations). Never estimated or backfilled.
    net_value_sample_size: int
    net_value_total: Decimal
    tax_value_sample_size: int
    tax_value_total: Decimal
    gross_value_sample_size: int
    gross_value_total: Decimal


def compute_po_financial_analysis(session: Session) -> PoFinancialAnalysis:
    client_award_evidence = session.execute(select(ClientAwardEvidence).where(ClientAwardEvidence.is_deleted.is_(False))).scalars().all()
    net_values = [po.net_value for po in client_award_evidence if po.net_value is not None]
    tax_values = [po.tax_value for po in client_award_evidence if po.tax_value is not None]
    gross_values = [po.gross_value for po in client_award_evidence if po.gross_value is not None]
    return PoFinancialAnalysis(
        client_award_evidence_count=len(client_award_evidence),
        net_value_sample_size=len(net_values),
        net_value_total=sum(net_values, ZERO),
        tax_value_sample_size=len(tax_values),
        tax_value_total=sum(tax_values, ZERO),
        gross_value_sample_size=len(gross_values),
        gross_value_total=sum(gross_values, ZERO),
    )


# --- 7. Currency breakdown -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CurrencyBreakdown:
    currency: Currency
    document_count: int
    value_total: Decimal


def compute_quotation_currency_breakdown(session: Session) -> list[CurrencyBreakdown]:
    quotations = _non_deleted_quotations(session)
    current_versions = _current_versions_by_quotation(session, [q.id for q in quotations])

    buckets: dict[Currency, dict] = {}
    for version in current_versions.values():
        bucket = buckets.setdefault(version.currency, {"count": 0, "total": ZERO})
        bucket["count"] += 1
        if version.quoted_value is not None:
            bucket["total"] += version.quoted_value

    return [
        CurrencyBreakdown(currency=currency, document_count=bucket["count"], value_total=bucket["total"])
        for currency, bucket in buckets.items()
    ]


def compute_po_currency_breakdown(session: Session) -> list[CurrencyBreakdown]:
    client_award_evidence = session.execute(select(ClientAwardEvidence).where(ClientAwardEvidence.is_deleted.is_(False))).scalars().all()

    buckets: dict[Currency, dict] = {}
    for po in client_award_evidence:
        bucket = buckets.setdefault(po.currency, {"count": 0, "total": ZERO})
        bucket["count"] += 1
        if po.net_value is not None:
            bucket["total"] += po.net_value

    return [
        CurrencyBreakdown(currency=currency, document_count=bucket["count"], value_total=bucket["total"])
        for currency, bucket in buckets.items()
    ]
