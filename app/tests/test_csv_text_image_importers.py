from __future__ import annotations

from pathlib import Path

from app.importers.csv_importer import CSVImporter
from app.importers.image_importer import ImageImporter
from app.importers.text_importer import TextImporter


def test_csv_import_parses_rows(tmp_path: Path) -> None:
    path = tmp_path / "boq.csv"
    path.write_text("Item,Description,Qty,Rate,Amount\n1,Excavation,100,50.00,5000.00\n", encoding="utf-8")

    result = CSVImporter().extract(path)

    assert not result.unsupported
    assert len(result.tables) == 1
    assert result.tables[0].rows[0] == ["Item", "Description", "Qty", "Rate", "Amount"]
    assert result.tables[0].rows[1][1] == "Excavation"


def test_csv_import_handles_semicolon_delimiter(tmp_path: Path) -> None:
    path = tmp_path / "boq_semicolon.csv"
    path.write_text("Item;Description;Amount\n1;Excavation;5000.00\n", encoding="utf-8")

    result = CSVImporter().extract(path)

    assert result.tables[0].rows[0] == ["Item", "Description", "Amount"]


def test_empty_csv_reports_warning(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    result = CSVImporter().extract(path)

    assert result.tables == []
    assert any("empty" in warning.lower() for warning in result.warnings)


def test_text_import_reads_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("Quotation Number: Q-1\nNet Amount: 500,000.00\n", encoding="utf-8")

    result = TextImporter().extract(path)

    assert result.text == "Quotation Number: Q-1\nNet Amount: 500,000.00\n"
    assert result.warnings == []


def test_empty_text_file_reports_warning(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")

    result = TextImporter().extract(path)

    assert any("empty" in warning.lower() for warning in result.warnings)


def test_image_import_always_requires_ocr(tmp_path: Path) -> None:
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG\r\n not a real png but content is irrelevant")

    result = ImageImporter().extract(path)

    assert result.requires_ocr is True
    assert result.unsupported is False
