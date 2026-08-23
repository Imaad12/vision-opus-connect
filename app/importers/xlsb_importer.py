"""Binary Excel (.xlsb) importer, via `pyxlsb`.

`.xlsb` stores calculated values directly (there is no cached-vs-live
formula distinction to choose between, unlike `.xlsx`), so every cell read
here is already a plain value. `pyxlsb` has no writer, which is also why
this format's test fixture is built differently — see
`app/tests/test_xlsb_importer.py` and IMPORT_ARCHITECTURE.md §4 for why.
"""

from __future__ import annotations

from pathlib import Path

from pyxlsb import open_workbook

from app.importers.base import BaseImporter, ExtractedTable, RawExtraction


def _cell_to_str(value: object) -> str:
    return "" if value is None else str(value)


class XLSBImporter(BaseImporter):
    extensions = ("xlsb",)

    def extract(self, path: Path) -> RawExtraction:
        warnings: list[str] = []
        tables: list[ExtractedTable] = []
        try:
            with open_workbook(str(path)) as workbook:
                for sheet_name in workbook.sheets:
                    with workbook.get_sheet(sheet_name) as sheet:
                        rows: list[list[str]] = []
                        for row in sheet.rows():
                            cells = [_cell_to_str(cell.v) for cell in row]
                            if any(cell.strip() for cell in cells):
                                rows.append(cells)
                        if rows:
                            tables.append(ExtractedTable(name=sheet_name, rows=rows))
        except Exception as exc:  # noqa: BLE001
            return RawExtraction(
                unsupported=True,
                unsupported_reason=f"Could not open .xlsb workbook (corrupt or unsupported): {exc}",
            )

        if not tables:
            warnings.append("No non-empty worksheets were found in this workbook.")
        return RawExtraction(tables=tables, warnings=warnings)
