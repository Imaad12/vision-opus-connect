from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, SoftDeleteMixin, TimestampMixin


class Contact(Base, TimestampMixin, SoftDeleteMixin):
    """A person at a client's organization -- distinct from `Client` itself
    (the account/company) and from `Lead` (a sales opportunity, which may
    reference a contact but is never the same record)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(150))
    department: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(200))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Contact(id={self.id!r}, client_id={self.client_id!r}, full_name={self.full_name!r})"
