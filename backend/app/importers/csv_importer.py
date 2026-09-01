"""CSV importer: a single table, read with the standard library `csv`
module. Encoding is guessed with a small fallback chain rather than
assumed, since exported BOQs/quotations arrive in whatever encoding the
originating spreadsheet tool used.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.importers.base import BaseImporter, ExtractedTable, RawExtraction

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1256", "latin-1")


def _read_text(path: Path) -> str:
    for encoding in _ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_text(encoding="latin-1", errors="replace")


class CSVImporter(BaseImporter):
    extensions = ("csv",)

    def extract(self, path: Path) -> RawExtraction:
        try:
            content = _read_text(path)
        except OSError as exc:
            return RawExtraction(unsupported=True, unsupported_reason=f"Could not read file: {exc}")

        try:
            dialect = csv.Sniffer().sniff(content[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

        reader = csv.reader(content.splitlines(), dialect=dialect)
        rows = [row for row in reader if any(cell.strip() for cell in row)]

        warnings: list[str] = []
        if not rows:
            warnings.append("This CSV file is empty.")

        return RawExtraction(tables=[ExtractedTable(name=None, rows=rows)] if rows else [], warnings=warnings)
