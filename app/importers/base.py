"""Historical document importer interface.

No format-specific parsing (PDF/Excel/Word) is implemented yet. This module
defines the shape every importer will produce, so that:

- adding a new source format later means writing one new class, not
  touching any calling code, and
- importing is always a reviewable staging step. `parse()` only produces
  candidate data plus warnings; it never writes to the database directly.
  A future service layer is responsible for presenting `ImportResult` to a
  user for review before persisting anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from app.core.enums import Currency, DEFAULT_CURRENCY


class ImportedBoqLine(BaseModel):
    """A single BOQ line item as read from a source document.

    Fields are optional because historical documents are inconsistently
    structured — a partially-recognized line is still useful for a human
    reviewer to complete, rather than being dropped.
    """

    line_number: str | None = None
    description: str | None = None
    unit: str | None = None
    quantity: Decimal | None = None
    unit_rate: Decimal | None = None
    total: Decimal | None = None


class ImportResult(BaseModel):
    """Everything extracted from one source document, awaiting review.

    `warnings` surfaces anything the importer could not confidently parse
    (e.g. an ambiguous total, a merged cell) so a human reviews it before
    it becomes financial data.
    """

    source_path: Path
    project_name: str | None = None
    client_name: str | None = None
    quotation_reference: str | None = None
    currency: Currency = DEFAULT_CURRENCY
    quoted_value: Decimal | None = None
    boq_lines: list[ImportedBoqLine] = []
    warnings: list[str] = []


class BaseImporter(ABC):
    """Common interface for all historical-document importers."""

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Return True if this importer supports the given file."""

    @abstractmethod
    def parse(self, path: Path) -> ImportResult:
        """Extract structured data from a source document.

        Must not write to the database. The caller is responsible for
        presenting the result for review before persisting it via the
        services layer.
        """
