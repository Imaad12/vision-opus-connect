"""Quotation and quotation-revision management.

A quotation only becomes revenue when explicitly awarded — this module is
the single place that transition happens, so the UI can never "accidentally"
turn a quote into awarded contract value. Award sets `Project.contract_value`
exactly once (via `Project.winning_quotation_version_id`); everything after
that is a variation, never a re-edit of the award (see FINANCIAL_MODEL.md).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.enums import DEFAULT_CURRENCY, Currency, ProjectStatus, QuotationStatus
from app.models import BOQLineItem, Project, Quotation, QuotationVersion
from app.services.errors import ValidationError


def get_quotation(session: Session, quotation_id: int) -> Quotation | None:
    quotation = session.get(Quotation, quotation_id)
    if quotation is None or quotation.is_deleted:
        return None
    return quotation


def get_quotation_version(session: Session, version_id: int) -> QuotationVersion | None:
    version = session.get(QuotationVersion, version_id)
    if version is None or version.is_deleted:
        return None
    return version


def list_boq_line_items(session: Session, version: QuotationVersion) -> list[BOQLineItem]:
    """Read-only: BOQ line items are populated by the document-import
    pipeline (`app.services.import_service`), never edited by hand here --
    there is no manual BOQ-authoring service to reuse or duplicate."""
    if version.boq is None:
        return []
    stmt = (
        select(BOQLineItem)
        .where(BOQLineItem.boq_id == version.boq.id, BOQLineItem.is_deleted.is_(False))
        .order_by(BOQLineItem.id)
    )
    return list(session.execute(stmt).scalars().all())


def list_quotation_versions(session: Session, *, search: str | None = None) -> list[QuotationVersion]:
    """All quotation versions across all projects, newest first — the data
    behind the global Quotations page. Eagerly usable columns (project,
    quotation reference) are reached via the ORM relationships already
    loaded by SQLAlchemy's default lazy loading; for the modest data volumes
    this application handles, that is simple and correct."""
    stmt = (
        select(QuotationVersion)
        .join(Quotation, QuotationVersion.quotation_id == Quotation.id)
        .options(
            joinedload(QuotationVersion.quotation)
            .joinedload(Quotation.project)
            .joinedload(Project.client)
        )
        .where(QuotationVersion.is_deleted.is_(False), Quotation.is_deleted.is_(False))
        .order_by(QuotationVersion.id.desc())
    )
    versions = list(session.execute(stmt).scalars().all())
    if search:
        needle = search.lower()
        versions = [
            v
            for v in versions
            if needle in (v.quotation.reference_number or "").lower()
            or needle in (v.quotation.project.name or "").lower()
        ]
    return versions


def list_quotations_for_project(session: Session, project_id: int) -> list[Quotation]:
    stmt = (
        select(Quotation)
        .where(Quotation.project_id == project_id, Quotation.is_deleted.is_(False))
        .order_by(Quotation.id)
    )
    return list(session.execute(stmt).scalars().all())


def list_versions_for_quotation(session: Session, quotation_id: int) -> list[QuotationVersion]:
    stmt = (
        select(QuotationVersion)
        .where(QuotationVersion.quotation_id == quotation_id, QuotationVersion.is_deleted.is_(False))
        .order_by(QuotationVersion.version_number)
    )
    return list(session.execute(stmt).scalars().all())


def get_current_version(session: Session, quotation: Quotation) -> QuotationVersion | None:
    """The chronologically most recent version of this quotation — ordered
    by `issued_date` (nulls last), then `id` as a deterministic tiebreak.

    Deliberately NOT the highest `version_number`: a revision can be
    confirmed out of chronological order (see
    `app.services.import_service.confirm_import`'s revision-conflict
    handling, which requires explicit acknowledgement before that's
    allowed to happen at all). "Current" always means "most recent by the
    date on the document," never "most recently entered into the system."
    """
    stmt = (
        select(QuotationVersion)
        .where(QuotationVersion.quotation_id == quotation.id, QuotationVersion.is_deleted.is_(False))
        .order_by(QuotationVersion.issued_date.desc().nulls_last(), QuotationVersion.id.desc())
    )
    return session.execute(stmt).scalars().first()


def create_quotation(
    session: Session,
    project: Project,
    *,
    reference_number: str | None = None,
    title: str | None = None,
    quoted_value: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    issued_date: date | None = None,
    valid_until: date | None = None,
    notes: str | None = None,
) -> QuotationVersion:
    """Create a new Quotation for a project along with its first version (v1)."""
    if quoted_value is not None and quoted_value < 0:
        raise ValidationError("Quoted value cannot be negative.")

    quotation = Quotation(
        project_id=project.id,
        reference_number=(reference_number or "").strip() or None,
        title=(title or "").strip() or None,
    )
    session.add(quotation)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ValidationError(f"Quotation reference '{reference_number}' is already in use.") from exc

    version = QuotationVersion(
        quotation_id=quotation.id,
        version_number=1,
        status=QuotationStatus.DRAFT,
        quoted_value=quoted_value,
        currency=currency,
        issued_date=issued_date,
        valid_until=valid_until,
        notes=(notes or "").strip() or None,
    )
    session.add(version)
    session.flush()
    return version


def create_quotation_revision(
    session: Session,
    quotation: Quotation,
    *,
    quoted_value: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    issued_date: date | None = None,
    valid_until: date | None = None,
    notes: str | None = None,
) -> QuotationVersion:
    """Add a new revision to an existing quotation. The prior version is
    never edited — this is what keeps quotation history auditable."""
    if quoted_value is not None and quoted_value < 0:
        raise ValidationError("Quoted value cannot be negative.")

    existing = list_versions_for_quotation(session, quotation.id)
    next_number = existing[-1].version_number + 1 if existing else 1

    version = QuotationVersion(
        quotation_id=quotation.id,
        version_number=next_number,
        status=QuotationStatus.DRAFT,
        quoted_value=quoted_value,
        currency=currency,
        issued_date=issued_date,
        valid_until=valid_until,
        notes=(notes or "").strip() or None,
    )
    session.add(version)
    session.flush()
    return version


def mark_submitted(session: Session, version: QuotationVersion) -> QuotationVersion:
    version.status = QuotationStatus.SUBMITTED
    project = version.quotation.project
    if project.status == ProjectStatus.LEAD:
        project.status = ProjectStatus.SUBMITTED
    session.flush()
    return version


def mark_lost(session: Session, version: QuotationVersion) -> QuotationVersion:
    version.status = QuotationStatus.LOST
    session.flush()
    return version


def mark_withdrawn(session: Session, version: QuotationVersion) -> QuotationVersion:
    version.status = QuotationStatus.WITHDRAWN
    session.flush()
    return version


def mark_awarded(session: Session, version: QuotationVersion, *, contract_value: Decimal) -> QuotationVersion:
    """Award this quotation version: the ONLY way `Project.contract_value`
    is ever set. It is deliberately not re-editable afterward — a change to
    the awarded value after this point is a `ProjectVariation`, not an edit
    to the original award (see FINANCIAL_MODEL.md's original-vs-revised
    contract value distinction).
    """
    if contract_value is None or contract_value <= 0:
        raise ValidationError("Awarded contract value must be a positive amount.")

    project = version.quotation.project
    if project.contract_value is not None:
        raise ValidationError(
            "This project already has an awarded contract value. "
            "Record further changes as a contract variation, not a re-award."
        )

    version.status = QuotationStatus.WON
    project.contract_value = contract_value
    project.contract_currency = version.currency
    project.winning_quotation_version_id = version.id
    if project.award_date is None:
        project.award_date = date.today()
    project.status = ProjectStatus.AWARDED
    session.flush()
    return version
