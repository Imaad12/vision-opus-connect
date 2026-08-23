"""Document importer interface and registry (Phase 4).

Every importer turns one local file into a `RawExtraction` — exactly what
the parser found, with nothing normalized or interpreted yet (see
IMPORT_ARCHITECTURE.md §5 for the raw-vs-normalized distinction). An
importer never touches the database and never decides what the extracted
data "means" business-wise; that is `app.core.import_extraction`'s job,
one layer up.

Each importer is a small, independent class registered by file extension.
Adding a new format later means writing one new class and registering it
here — nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractedTable:
    """One table found in a source document — a worksheet, a Word table, a
    PDF table-like block. `name` is a sheet/section label where one exists."""

    name: str | None
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class RawExtraction:
    """Everything one importer found in one file, before any business
    interpretation. `text` is the flattened plain-text content (PDFs,
    Word, plain text files); `tables` covers Excel sheets and Word/PDF
    tables. Both may be populated for the same document.

    `requires_ocr` and `unsupported` are terminal states: when either is
    True, `app.services.import_service` stops before attempting to derive
    any candidate business data, exactly as the brief requires ("do not
    silently create incorrect financial records from poor extraction").
    """

    text: str | None = None
    tables: list[ExtractedTable] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_ocr: bool = False
    unsupported: bool = False
    unsupported_reason: str | None = None


class BaseImporter(ABC):
    """Common interface for all document importers."""

    #: Lower-case file extensions this importer claims, without the dot.
    extensions: tuple[str, ...] = ()

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") in self.extensions

    @abstractmethod
    def extract(self, path: Path) -> RawExtraction:
        """Read `path` (never modifying it) and return what was found.

        Must not raise for "the document just doesn't have useful data" —
        that is expressed as an empty/near-empty `RawExtraction`, or
        `requires_ocr`/`unsupported`. Callers (import_service) still guard
        against unexpected exceptions from corrupt/malformed files, but an
        importer should prefer a clear, structured result whenever
        possible.
        """


class ImporterRegistry:
    """Maps a file extension to the importer that handles it."""

    def __init__(self) -> None:
        self._importers: list[BaseImporter] = []

    def register(self, importer: BaseImporter) -> None:
        self._importers.append(importer)

    def find_for(self, path: Path) -> BaseImporter | None:
        for importer in self._importers:
            if importer.can_handle(path):
                return importer
        return None

    def supported_extensions(self) -> set[str]:
        extensions: set[str] = set()
        for importer in self._importers:
            extensions.update(importer.extensions)
        return extensions


def build_default_registry() -> ImporterRegistry:
    """The registry used by the running application. A separate factory
    (rather than a module-level singleton) keeps tests able to build a
    fresh, isolated registry when needed."""
    from app.importers.csv_importer import CSVImporter
    from app.importers.excel_importer import ExcelImporter
    from app.importers.image_importer import ImageImporter
    from app.importers.pdf_importer import PDFImporter
    from app.importers.text_importer import TextImporter
    from app.importers.word_importer import WordImporter
    from app.importers.xlsb_importer import XLSBImporter

    registry = ImporterRegistry()
    registry.register(PDFImporter())
    registry.register(ExcelImporter())
    registry.register(XLSBImporter())
    registry.register(WordImporter())
    registry.register(CSVImporter())
    registry.register(TextImporter())
    registry.register(ImageImporter())
    return registry
