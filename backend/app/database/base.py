"""Shared SQLAlchemy declarative base and audit/soft-delete mixins."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base every ORM model inherits from."""


class TimestampMixin:
    """created_at / updated_at columns, maintained by the database itself."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """is_deleted / deleted_at columns for records that must never be hard-deleted.

    Used by business/financial tables so a user "deleting" a record never
    destroys audit history; lookup tables (Trade, CostCategory, Company) and
    GoogleDriveDocument do not use this mixin since they carry no
    independent financial history.
    """

    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
