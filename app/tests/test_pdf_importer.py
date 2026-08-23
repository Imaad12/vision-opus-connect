"""PDFImporter tests, using small synthetic PDFs built with PyMuPDF itself
at test time — never a real company document.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf

from app.importers.pdf_importer import PDFImporter


def _write_text_pdf(path: Path, text: str) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(36, 36, 560, 700), text, fontsize=11)
    document.save(path)
    document.close()


def test_text_pdf_extracts_text(tmp_path: Path) -> None:
    path = tmp_path / "quotation.pdf"
    _write_text_pdf(path, "Quotation Number: Q-100\nNet Amount: AED 500,000.00\n")

    result = PDFImporter().extract(path)

    assert not result.unsupported
    assert not result.requires_ocr
    assert result.text is not None
    assert "Quotation Number" in result.text
    assert "Q-100" in result.text


def test_scanned_pdf_with_no_text_requires_ocr(tmp_path: Path) -> None:
    path = tmp_path / "scanned.pdf"
    document = pymupdf.open()
    document.new_page()  # a blank page: no text layer at all
    document.save(path)
    document.close()

    result = PDFImporter().extract(path)

    assert result.requires_ocr is True
    assert result.text is None


def test_password_protected_pdf_is_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "protected.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Confidential quotation")
    document.save(
        path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    document.close()

    result = PDFImporter().extract(path)

    assert result.unsupported is True
    assert "password" in (result.unsupported_reason or "").lower()


def test_zero_page_pdf_is_handled_without_crashing(tmp_path: Path) -> None:
    # PyMuPDF (and every other PDF writer) refuses to save a real zero-page
    # PDF file ("cannot save with zero pages"), so there is no way to
    # produce a genuine on-disk fixture for this edge case. This mocks the
    # opened document instead, to exercise the `page_count == 0` guard in
    # PDFImporter.extract deterministically.
    path = tmp_path / "zero_pages.pdf"
    path.write_bytes(b"placeholder")

    fake_document = MagicMock()
    fake_document.needs_pass = False
    fake_document.page_count = 0

    with patch("app.importers.pdf_importer.pymupdf.open", return_value=fake_document):
        result = PDFImporter().extract(path)

    assert not result.unsupported
    assert not result.requires_ocr
    assert any("no pages" in warning.lower() for warning in result.warnings)


def test_corrupt_pdf_is_reported_as_unsupported_not_crashed(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.4 this is not a real pdf body")

    result = PDFImporter().extract(path)

    assert result.unsupported is True
    assert result.unsupported_reason
