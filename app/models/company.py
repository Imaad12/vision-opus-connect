from __future__ import annotations

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DEFAULT_CURRENCY, Currency
from app.database.base import Base, TimestampMixin


class Company(Base, TimestampMixin):
    """A legal entity of Vision Contracting executing projects."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    trade_license_number: Mapped[str | None] = mapped_column(String(100))
    default_currency: Mapped[Currency] = mapped_column(
        SAEnum(Currency, native_enum=False), default=DEFAULT_CURRENCY, nullable=False
    )
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Company(id={self.id!r}, name={self.name!r})"
