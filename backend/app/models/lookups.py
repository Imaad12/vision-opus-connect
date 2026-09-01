"""Small lookup tables: Trade and CostCategory."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Trade(Base, TimestampMixin):
    """A classification of construction work, e.g. Electrical, Plumbing, Civil."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)

    def __repr__(self) -> str:
        return f"Trade(id={self.id!r}, name={self.name!r})"


class CostCategory(Base, TimestampMixin):
    """A classification of cost, e.g. Labor, Material, Equipment, Subcontract."""

    __tablename__ = "cost_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("cost_categories.id"))

    def __repr__(self) -> str:
        return f"CostCategory(id={self.id!r}, name={self.name!r})"
