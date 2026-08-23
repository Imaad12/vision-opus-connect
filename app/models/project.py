from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DEFAULT_CURRENCY, Currency, ProjectStatus
from app.database.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.client import Client


class Project(Base, TimestampMixin, SoftDeleteMixin):
    """A construction project — the central entity of the system."""

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("project_code", name="uq_projects_project_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_code: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    primary_trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"))
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus, native_enum=False),
        default=ProjectStatus.LEAD,
        nullable=False,
    )

    tender_submission_date: Mapped[date | None] = mapped_column(Date)
    award_date: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date | None] = mapped_column(Date)
    planned_completion_date: Mapped[date | None] = mapped_column(Date)
    actual_completion_date: Mapped[date | None] = mapped_column(Date)
    defects_liability_end_date: Mapped[date | None] = mapped_column(Date)

    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    contract_currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    # use_alter breaks the circular FK cycle projects -> quotation_versions -> quotations -> projects
    winning_quotation_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_versions.id", use_alter=True, name="fk_projects_winning_quotation_version")
    )

    notes: Mapped[str | None] = mapped_column(Text)

    client: Mapped["Client"] = relationship("Client", foreign_keys=[client_id])

    def __repr__(self) -> str:
        return f"Project(id={self.id!r}, name={self.name!r}, status={self.status!r})"


class ProjectStatusHistory(Base, TimestampMixin):
    """Audit trail of Project.status changes."""

    __tablename__ = "project_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(SAEnum(ProjectStatus, native_enum=False), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"ProjectStatusHistory(project_id={self.project_id!r}, status={self.status!r})"
