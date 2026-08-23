"""XLSBImporter tests.

There is no pure-Python writer for the .xlsb binary format (`pyxlsb` is
read-only, and no other maintained library can produce one) — a real
`.xlsb` fixture can only practically be produced by Excel itself, which
this repository cannot do in CI or generate synthetically. Per the Phase 4
testing brief ("clearly document why the test requires a manually
supplied fixture"), this test instead verifies the importer's own parsing
logic by faking `pyxlsb`'s reader API with `unittest.mock` — the same rows
a real `.xlsb` workbook would hand back — so the column-mapping and
error-handling code paths are still exercised deterministically without a
binary fixture.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.importers.xlsb_importer import XLSBImporter


class _FakeCell:
    def __init__(self, value: object) -> None:
        self.v = value


def _fake_workbook(sheets: dict[str, list[list[object]]]) -> MagicMock:
    workbook = MagicMock()
    workbook.sheets = list(sheets.keys())
    workbook.__enter__.return_value = workbook
    workbook.__exit__.return_value = False

    def get_sheet(name: str) -> MagicMock:
        sheet = MagicMock()
        sheet.__enter__.return_value = sheet
        sheet.__exit__.return_value = False
        sheet.rows.return_value = [[_FakeCell(v) for v in row] for row in sheets[name]]
        return sheet

    workbook.get_sheet.side_effect = get_sheet
    return workbook


def test_xlsb_import_reads_rows_from_mocked_workbook(tmp_path: Path) -> None:
    path = tmp_path / "quote.xlsb"
    path.write_bytes(b"placeholder")  # content is irrelevant; open_workbook is mocked

    fake_workbook = _fake_workbook(
        {
            "BOQ": [
                ["Item", "Description", "Unit", "Qty", "Rate", "Amount"],
                ["1", "Excavation", "m3", 100, 50.0, 5000.0],
            ]
        }
    )

    with patch("app.importers.xlsb_importer.open_workbook", return_value=fake_workbook):
        result = XLSBImporter().extract(path)

    assert not result.unsupported
    assert len(result.tables) == 1
    assert result.tables[0].name == "BOQ"
    assert result.tables[0].rows[1][1] == "Excavation"


def test_xlsb_import_reports_unsupported_on_open_failure(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.xlsb"
    path.write_bytes(b"not a real xlsb file")

    with patch("app.importers.xlsb_importer.open_workbook", side_effect=OSError("bad file")):
        result = XLSBImporter().extract(path)

    assert result.unsupported is True
    assert result.unsupported_reason


def test_xlsb_import_reports_empty_workbook(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsb"
    path.write_bytes(b"placeholder")

    with patch("app.importers.xlsb_importer.open_workbook", return_value=_fake_workbook({"Sheet1": []})):
        result = XLSBImporter().extract(path)

    assert not result.unsupported
    assert result.tables == []
    assert any("no non-empty worksheets" in warning.lower() for warning in result.warnings)
