"""Pydantic schemas for the People domain: Employee, PayrollRecord."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Currency, EmploymentStatus, PayrollStatus


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    position: str | None
    department: str | None
    phone: str | None
    email: str | None
    hire_date: date | None
    termination_date: date | None
    employment_status: EmploymentStatus
    base_salary: Decimal | None
    currency: Currency
    notes: str | None
    created_at: datetime
    updated_at: datetime


class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=1)
    position: str | None = None
    department: str | None = None
    phone: str | None = None
    email: str | None = None
    hire_date: date | None = None
    termination_date: date | None = None
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    base_salary: Decimal | None = None
    currency: Currency = Currency.AED
    notes: str | None = None


class EmployeeUpdate(EmployeeCreate):
    pass


class PayrollRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    period_start: date
    period_end: date
    gross_amount: Decimal
    deductions: Decimal
    net_amount: Decimal
    currency: Currency
    status: PayrollStatus
    paid_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class PayrollRecordCreate(BaseModel):
    employee_id: int
    period_start: date
    period_end: date
    gross_amount: Decimal = Field(ge=0)
    deductions: Decimal = Decimal("0.00")
    currency: Currency = Currency.AED
    notes: str | None = None


class PayrollMarkPaid(BaseModel):
    paid_date: date
