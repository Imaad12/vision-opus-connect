"""Projects -- backed entirely by the existing `project_service`, which
already owns validation (name/client required, date ordering,
project-code uniqueness) and company resolution. This router adds no
rules of its own.

Known gap, deliberately not papered over: the frontend's `projects.tsx`
form also collects `manager_id`, `location`, `budget_cost`, and
`progress_percent`, and lets the user type `contract_value` directly.
None of these are accepted by `create_project`/`update_project` --
`contract_value` in particular is set exactly once, by
`quotation_service.mark_awarded`, never by direct edit (see
FINANCIAL_MODEL.md). Wiring the frontend's project *form* needs that
distinction reflected in the UI (award happens on the Quotations screen,
not here), not an API that silently accepts and drops the value.
`ProjectStatus`'s real values (`LEAD/TENDERING/SUBMITTED/AWARDED/LOST/
IN_PROGRESS/ON_HOLD/COMPLETED/CLOSED/CANCELLED`) also don't match the
frontend's (`planning/active/on_hold/completed/archived/cancelled`) --
returned as-is here rather than silently renamed; the frontend's
integration layer maps between them explicitly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from app.core.enums import ProjectStatus
from app.services import project_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    search: str | None = None,
    status_filter: ProjectStatus | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("projects.view")),
) -> list[ProjectRead]:
    return list(project_service.list_projects(session, search=search, status=status_filter))


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("projects.view")),
) -> ProjectRead:
    project = project_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("projects.create")),
) -> ProjectRead:
    try:
        return project_service.create_project(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("projects.edit")),
) -> ProjectRead:
    project = project_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    try:
        return project_service.update_project(session, project, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
