"""Expenses -- the frontend's `expenses` module, backed by `ActualCost`.

Permission is `finance.expenses` (copied verbatim from the frontend's real
`app_permission` enum) -- the page previously used a non-existent
`expenses.view/create/edit/delete` vocabulary that never matched any real
permission, the same class of bug already found and fixed for
purchase-orders.tsx/approvals.tsx.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_finance import ExpenseCreate, ExpenseRead, ExpenseUpdate
from app.services import cost_service
from app.services.errors import ValidationError
from app.services.project_service import get_project

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.get("", response_model=list[ExpenseRead])
def list_expenses(
    project_id: int | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.expenses")),
) -> list[ExpenseRead]:
    return list(cost_service.list_expenses(session, project_id=project_id))


@router.get("/{expense_id}", response_model=ExpenseRead)
def get_expense(
    expense_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.expenses")),
) -> ExpenseRead:
    expense = cost_service.get_actual_cost(session, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found.")
    return expense


@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.expenses")),
) -> ExpenseRead:
    project = get_project(session, payload.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Select a valid project.")
    fields = payload.model_dump(exclude={"project_id"})
    try:
        return cost_service.add_actual_cost(session, project, **fields)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{expense_id}", response_model=ExpenseRead)
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("finance.expenses")),
) -> ExpenseRead:
    expense = cost_service.get_actual_cost(session, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found.")
    try:
        return cost_service.update_actual_cost(session, expense, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
