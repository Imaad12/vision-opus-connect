from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DEFAULT_CURRENCY, Currency, EmploymentStatus, PayrollStatus
from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class Employee(Base, TimestampMixin, SoftDeleteMixin):
    """An HR roster entry.

    Deliberately unrelated to Supabase's `profiles`/`user_roles` tables
    (the app-login identities behind `nav.employees` in the frontend,
    gated by `admin.users`/`admin.roles`): a person can be tracked here as
    a payroll subject without ever having application login access, and
    vice versa. This is the real `employees.view`/`employees.manage`
    permission's intended resource.
    """

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[str | None] = mapped_column(String(150))
    department: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(200))
    hire_date: Mapped[date | None] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        SAEnum(EmploymentStatus, native_enum=False),
        default=EmploymentStatus.ACTIVE,
        server_default=EmploymentStatus.ACTIVE.value,
        nullable=False,
    )
    base_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Employee(id={self.id!r}, full_name={self.full_name!r})"


class PayrollRecord(Base, TimestampMixin, SoftDeleteMixin):
    """One pay period's payroll for one employee.

    `net_amount` is always `gross_amount - deductions`, recomputed by
    the service layer whenever either changes (never entered directly),
    mirroring the pattern already used for PurchaseOrder totals.
    """

    __tablename__ = "payroll_records"
    __table_args__ = (
        CheckConstraint("period_end >= period_start", name="ck_payroll_records_period_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    deductions: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), server_default="0.00", nullable=False
    )
    net_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    status: Mapped[PayrollStatus] = mapped_column(
        SAEnum(PayrollStatus, native_enum=False),
        default=PayrollStatus.DRAFT,
        server_default=PayrollStatus.DRAFT.value,
        nullable=False,
    )
    paid_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"PayrollRecord(id={self.id!r}, employee_id={self.employee_id!r}, net_amount={self.net_amount!r})"
