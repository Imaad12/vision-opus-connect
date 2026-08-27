"""Employee (HR roster) CRUD. Mirrors `vendor_service.py`'s shape."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DEFAULT_CURRENCY, Currency, EmploymentStatus
from app.models import Employee
from app.services.errors import ValidationError

__all__ = ["ValidationError", "list_employees", "get_employee", "create_employee", "update_employee"]


def list_employees(session: Session, *, search: str | None = None) -> list[Employee]:
    stmt = select(Employee).where(Employee.is_deleted.is_(False))
    if search:
        stmt = stmt.where(Employee.full_name.ilike(f"%{search}%"))
    stmt = stmt.order_by(Employee.full_name)
    return list(session.execute(stmt).scalars().all())


def get_employee(session: Session, employee_id: int) -> Employee | None:
    employee = session.get(Employee, employee_id)
    if employee is None or employee.is_deleted:
        return None
    return employee


def create_employee(
    session: Session,
    *,
    full_name: str,
    position: str | None = None,
    department: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    hire_date: date | None = None,
    termination_date: date | None = None,
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE,
    base_salary: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    notes: str | None = None,
) -> Employee:
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationError("Employee name is required.")
    if termination_date is not None and hire_date is not None and termination_date < hire_date:
        raise ValidationError("Termination date cannot be before the hire date.")

    employee = Employee(
        full_name=full_name,
        position=(position or "").strip() or None,
        department=(department or "").strip() or None,
        phone=(phone or "").strip() or None,
        email=(email or "").strip() or None,
        hire_date=hire_date,
        termination_date=termination_date,
        employment_status=employment_status,
        base_salary=base_salary,
        currency=currency,
        notes=(notes or "").strip() or None,
    )
    session.add(employee)
    session.flush()
    return employee


def update_employee(
    session: Session,
    employee: Employee,
    *,
    full_name: str,
    position: str | None = None,
    department: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    hire_date: date | None = None,
    termination_date: date | None = None,
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE,
    base_salary: Decimal | None = None,
    currency: Currency = DEFAULT_CURRENCY,
    notes: str | None = None,
) -> Employee:
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationError("Employee name is required.")
    if termination_date is not None and hire_date is not None and termination_date < hire_date:
        raise ValidationError("Termination date cannot be before the hire date.")

    employee.full_name = full_name
    employee.position = (position or "").strip() or None
    employee.department = (department or "").strip() or None
    employee.phone = (phone or "").strip() or None
    employee.email = (email or "").strip() or None
    employee.hire_date = hire_date
    employee.termination_date = termination_date
    employee.employment_status = employment_status
    employee.base_salary = base_salary
    employee.currency = currency
    employee.notes = (notes or "").strip() or None
    session.flush()
    return employee
