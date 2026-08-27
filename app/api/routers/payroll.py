"""Payroll records. No frontend page consumes this yet -- see
API_ARCHITECTURE.md Milestone 2 notes -- gated behind `employees.manage`
since it is HR-only, not a general finance record."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas_people import PayrollMarkPaid, PayrollRecordCreate, PayrollRecordRead
from app.services import payroll_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/payroll-records", tags=["payroll"])


@router.get("", response_model=list[PayrollRecordRead])
def list_payroll_records(
    employee_id: int | None = None,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.manage")),
) -> list[PayrollRecordRead]:
    return list(payroll_service.list_payroll_records(session, employee_id=employee_id))


@router.get("/{record_id}", response_model=PayrollRecordRead)
def get_payroll_record(
    record_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.manage")),
) -> PayrollRecordRead:
    record = payroll_service.get_payroll_record(session, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll record not found.")
    return record


@router.post("", response_model=PayrollRecordRead, status_code=status.HTTP_201_CREATED)
def create_payroll_record(
    payload: PayrollRecordCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.manage")),
) -> PayrollRecordRead:
    try:
        return payroll_service.create_payroll_record(session, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{record_id}/approve", response_model=PayrollRecordRead)
def approve_payroll_record(
    record_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.manage")),
) -> PayrollRecordRead:
    record = payroll_service.get_payroll_record(session, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll record not found.")
    try:
        return payroll_service.approve_payroll_record(session, record)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{record_id}/pay", response_model=PayrollRecordRead)
def mark_payroll_paid(
    record_id: int,
    payload: PayrollMarkPaid,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("employees.manage")),
) -> PayrollRecordRead:
    record = payroll_service.get_payroll_record(session, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll record not found.")
    try:
        return payroll_service.mark_payroll_paid(session, record, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
