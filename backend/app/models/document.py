from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DocumentType
from app.database.base import Base, TimestampMixin


class GoogleDriveDocument(Base, TimestampMixin):
    """A reference to a file stored in Google Drive.

    Stores metadata only — never file content, and never financial figures
    extracted from the document without going through the normal
    data-entry/import path. Hard-deletable since it carries no independent
    financial history (re-syncable from Drive).
    """

    __tablename__ = "google_drive_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    quotation_version_id: Mapped[int | None] = mapped_column(ForeignKey("quotation_versions.id"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, native_enum=False), nullable=False
    )
    drive_file_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    web_link: Mapped[str | None] = mapped_column(String(1000))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return f"GoogleDriveDocument(id={self.id!r}, drive_file_id={self.drive_file_id!r})"
