"""Employees (HR roster) -- a new frontend module, not the existing
`/employees` RBAC-admin screen (which manages Supabase `profiles`/
`user_roles` directly and stays there deliberately -- see
`app/models/employee.py`). Permissions are the real, previously-unused
`employees.view`/`employees.manage` from the frontend's `app_permission`
enum."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_people import EmployeeCreate, EmployeeRead, EmployeeUpdate
from app.services import employee_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeRead])
def list_employees(
    search: str | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.view")),
) -> list[EmployeeRead]:
    return list(employee_service.list_employees(session, search=search))


@router.get("/{employee_id}", response_model=EmployeeRead)
def get_employee(
    employee_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.view")),
) -> EmployeeRead:
    employee = employee_service.get_employee(session, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")
    return employee


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.manage")),
) -> EmployeeRead:
    try:
        return employee_service.create_employee(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.manage")),
) -> EmployeeRead:
    employee = employee_service.get_employee(session, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")
    try:
        return employee_service.update_employee(session, employee, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
