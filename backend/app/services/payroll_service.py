"""Payroll record CRUD and lifecycle: `DRAFT -> APPROVED -> PAID`.

No frontend page consumes this yet (see API_ARCHITECTURE.md Milestone 2
notes) -- built as a real, tested backend domain so the HR roster isn't
payroll-shaped without actual payroll, matching the "employees/payroll"
scope of Milestone 2, without inventing UI ahead of a concrete page.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DEFAULT_CURRENCY, Currency, PayrollStatus
from app.models import Employee, PayrollRecord
from app.services.errors import ValidationError

__all__ = [
    "ValidationError",
    "list_payroll_records",
    "get_payroll_record",
    "create_payroll_record",
    "approve_payroll_record",
    "mark_payroll_paid",
]


def list_payroll_records(session: Session, *, employee_id: int | None = None) -> list[PayrollRecord]:
    stmt = select(PayrollRecord).where(PayrollRecord.is_deleted.is_(False))
    if employee_id is not None:
        stmt = stmt.where(PayrollRecord.employee_id == employee_id)
    stmt = stmt.order_by(PayrollRecord.period_start.desc(), PayrollRecord.id.desc())
    return list(session.execute(stmt).scalars().all())


def get_payroll_record(session: Session, record_id: int) -> PayrollRecord | None:
    record = session.get(PayrollRecord, record_id)
    if record is None or record.is_deleted:
        return None
    return record


def create_payroll_record(
    session: Session,
    *,
    employee_id: int,
    period_start: date,
    period_end: date,
    gross_amount: Decimal,
    deductions: Decimal = Decimal("0.00"),
    currency: Currency = DEFAULT_CURRENCY,
    notes: str | None = None,
) -> PayrollRecord:
    employee = session.get(Employee, employee_id)
    if employee is None or employee.is_deleted:
        raise ValidationError("Select a valid employee.")
    if period_end < period_start:
        raise ValidationError("Period end cannot be before period start.")
    if gross_amount < 0:
        raise ValidationError("Gross amount cannot be negative.")
    if deductions < 0:
        raise ValidationError("Deductions cannot be negative.")
    if deductions > gross_amount:
        raise ValidationError("Deductions cannot exceed the gross amount.")

    record = PayrollRecord(
        employee_id=employee_id,
        period_start=period_start,
        period_end=period_end,
        gross_amount=gross_amount,
        deductions=deductions,
        net_amount=gross_amount - deductions,
        currency=currency,
        status=PayrollStatus.DRAFT,
        notes=(notes or "").strip() or None,
    )
    session.add(record)
    session.flush()
    return record


def approve_payroll_record(session: Session, record: PayrollRecord) -> PayrollRecord:
    if record.status != PayrollStatus.DRAFT:
        raise ValidationError("Only a draft payroll record can be approved.")
    record.status = PayrollStatus.APPROVED
    session.flush()
    return record


def mark_payroll_paid(session: Session, record: PayrollRecord, *, paid_date: date) -> PayrollRecord:
    if record.status != PayrollStatus.APPROVED:
        raise ValidationError("Only an approved payroll record can be marked paid.")
    record.status = PayrollStatus.PAID
    record.paid_date = paid_date
    session.flush()
    return record
