"""Plain text importer: .txt files, read as flat text (no table structure)."""

from __future__ import annotations

from pathlib import Path

from app.importers.base import BaseImporter, RawExtraction

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1256", "latin-1")


class TextImporter(BaseImporter):
    extensions = ("txt",)

    def extract(self, path: Path) -> RawExtraction:
        for encoding in _ENCODINGS:
            try:
                content = path.read_text(encoding=encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            content = path.read_text(encoding="latin-1", errors="replace")

        warnings = [] if content.strip() else ["This text file is empty."]
        return RawExtraction(text=content or None, warnings=warnings)
