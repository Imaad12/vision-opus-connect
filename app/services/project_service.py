"""Project CRUD, search/filtering, and the project-list financial view.

Business rules (validation, uniqueness, date ordering) live here — never in
the UI. Financial figures are never computed here; they're always obtained
from `app.services.financial_service`, which in turn only ever calls into
`app.core.financial_engine`. This module's job is limited to the Project
row itself and to combining it with a snapshot for display.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.enums import Currency, DEFAULT_CURRENCY, ProjectStatus
from app.core.financial_engine import ProjectFinancialSnapshot
from app.models import Client, Company, Project
from app.services.errors import ValidationError
from app.services.financial_service import build_project_financial_snapshot

DEFAULT_COMPANY_NAME = "Vision Contracting Company"

ACTIVE_STATUSES = (
    ProjectStatus.LEAD,
    ProjectStatus.TENDERING,
    ProjectStatus.SUBMITTED,
    ProjectStatus.AWARDED,
    ProjectStatus.IN_PROGRESS,
    ProjectStatus.ON_HOLD,
)
COMPLETED_STATUSES = (ProjectStatus.COMPLETED, ProjectStatus.CLOSED)


def count_active_projects(session: Session) -> int:
    """Number of projects that have not been soft-deleted."""
    stmt = select(func.count()).select_from(Project).where(Project.is_deleted.is_(False))
    return session.execute(stmt).scalar_one()


def get_or_create_default_company(session: Session) -> Company:
    """This is a single-company desktop application: there is exactly one
    `Company` row, created transparently on first use so project creation
    never has to ask the user to pick or set one up."""
    company = session.execute(select(Company).limit(1)).scalars().first()
    if company is not None:
        return company

    company = Company(name=DEFAULT_COMPANY_NAME, default_currency=DEFAULT_CURRENCY)
    session.add(company)
    session.flush()
    return company


def get_project(session: Session, project_id: int) -> Project | None:
    project = session.get(Project, project_id)
    if project is None or project.is_deleted:
        return None
    return project


def list_projects(
    session: Session,
    *,
    search: str | None = None,
    status: ProjectStatus | None = None,
) -> list[Project]:
    stmt = select(Project).options(joinedload(Project.client)).where(Project.is_deleted.is_(False))
    if status is not None:
        stmt = stmt.where(Project.status == status)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.join(Client, Project.client_id == Client.id).where(
            Project.name.ilike(pattern) | Project.project_code.ilike(pattern) | Client.name.ilike(pattern)
        )
    stmt = stmt.order_by(Project.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def list_projects_with_snapshots(
    session: Session,
    *,
    search: str | None = None,
    status: ProjectStatus | None = None,
) -> list[tuple[Project, ProjectFinancialSnapshot]]:
    """The data behind the Projects list table: each project paired with its
    financial snapshot. One snapshot query-set per project (not a single
    giant join) — simple and correct, which matters more than raw query
    count at the scale a single contracting company operates at. See
    UI_ARCHITECTURE.md for the tradeoff."""
    projects = list_projects(session, search=search, status=status)
    return [(project, build_project_financial_snapshot(session, project)) for project in projects]


def _validate_dates(
    start_date: date | None, planned_completion_date: date | None, actual_completion_date: date | None
) -> None:
    if start_date and planned_completion_date and planned_completion_date < start_date:
        raise ValidationError("Expected completion date cannot be before the start date.")
    if start_date and actual_completion_date and actual_completion_date < start_date:
        raise ValidationError("Actual completion date cannot be before the start date.")


def create_project(
    session: Session,
    *,
    name: str,
    client_id: int,
    project_code: str | None = None,
    description: str | None = None,
    status: ProjectStatus = ProjectStatus.LEAD,
    currency: Currency = DEFAULT_CURRENCY,
    start_date: date | None = None,
    planned_completion_date: date | None = None,
    actual_completion_date: date | None = None,
    notes: str | None = None,
) -> Project:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Project name is required.")

    if client_id is None:
        raise ValidationError("Client is required.")
    client = session.get(Client, client_id)
    if client is None or client.is_deleted:
        raise ValidationError("Select a valid client.")

    project_code = (project_code or "").strip() or None
    _validate_dates(start_date, planned_completion_date, actual_completion_date)

    company = get_or_create_default_company(session)

    project = Project(
        company_id=company.id,
        client_id=client_id,
        name=name,
        project_code=project_code,
        description=(description or "").strip() or None,
        status=status,
        contract_currency=currency,
        start_date=start_date,
        planned_completion_date=planned_completion_date,
        actual_completion_date=actual_completion_date,
        notes=(notes or "").strip() or None,
    )
    session.add(project)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ValidationError(f"Project number '{project_code}' is already in use.") from exc
    return project


def update_project(
    session: Session,
    project: Project,
    *,
    name: str,
    client_id: int,
    project_code: str | None = None,
    description: str | None = None,
    status: ProjectStatus = ProjectStatus.LEAD,
    currency: Currency = DEFAULT_CURRENCY,
    start_date: date | None = None,
    planned_completion_date: date | None = None,
    actual_completion_date: date | None = None,
    notes: str | None = None,
) -> Project:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Project name is required.")

    if client_id is None:
        raise ValidationError("Client is required.")
    client = session.get(Client, client_id)
    if client is None or client.is_deleted:
        raise ValidationError("Select a valid client.")

    project_code = (project_code or "").strip() or None
    _validate_dates(start_date, planned_completion_date, actual_completion_date)

    project.client_id = client_id
    project.name = name
    project.project_code = project_code
    project.description = (description or "").strip() or None
    project.status = status
    project.contract_currency = currency
    project.start_date = start_date
    project.planned_completion_date = planned_completion_date
    project.actual_completion_date = actual_completion_date
    project.notes = (notes or "").strip() or None

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ValidationError(f"Project number '{project_code}' is already in use.") from exc
    return project
