"""Tests for `app.core.document_preview` -- the reusable page-preview
rendering utility (first consumer: the eventual Review Queue UI).

Uses the same real-`pymupdf`-PDF-fixture convention as
`test_ocr_extraction.py` rather than mocking PyMuPDF, so these tests
exercise the actual rendering path a reviewer would see.
"""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from app.core.document_preview import render_page_preview


def _make_pdf(path: Path, page_count: int) -> None:
    doc = pymupdf.open()
    for _ in range(page_count):
        doc.new_page()
    doc.save(path)
    doc.close()


def _make_pdf_with_text(path: Path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


# --- Valid rendering ----------------------------------------------------


def test_real_pdf_page_produces_valid_png_bytes(tmp_path: Path) -> None:
    pdf_path = tmp_path / "quotation.pdf"
    _make_pdf_with_text(pdf_path, "Quotation Number: VN/QU/412/18")

    image_bytes = render_page_preview(pdf_path, 1)

    assert image_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
    image = Image.open(io.BytesIO(image_bytes))
    image.verify()  # raises if PIL cannot decode it as a real image


def test_rendered_page_is_non_empty(tmp_path: Path) -> None:
    pdf_path = tmp_path / "single_page.pdf"
    _make_pdf(pdf_path, 1)

    image_bytes = render_page_preview(pdf_path, 1)

    assert len(image_bytes) > 0
    image = Image.open(io.BytesIO(image_bytes))
    width, height = image.size
    assert width > 0
    assert height > 0


def test_dpi_parameter_changes_rendered_pixel_dimensions(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sized.pdf"
    _make_pdf(pdf_path, 1)

    low_dpi = render_page_preview(pdf_path, 1, dpi=72)
    high_dpi = render_page_preview(pdf_path, 1, dpi=150)

    low_size = Image.open(io.BytesIO(low_dpi)).size
    high_size = Image.open(io.BytesIO(high_dpi)).size
    assert high_size[0] > low_size[0]
    assert high_size[1] > low_size[1]


def test_default_dpi_is_150() -> None:
    import inspect

    default_dpi = inspect.signature(render_page_preview).parameters["dpi"].default
    assert default_dpi == 150


def test_correct_page_is_rendered_from_a_multi_page_document(tmp_path: Path) -> None:
    # Distinguishable content per page (different amounts of text) so a
    # rendering of the wrong page would plausibly produce different bytes.
    pdf_path = tmp_path / "multipage.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Page one content")
    doc.new_page().insert_text((72, 72), "Page two has considerably more visible text on it")
    doc.save(pdf_path)
    doc.close()

    page_one_bytes = render_page_preview(pdf_path, 1)
    page_two_bytes = render_page_preview(pdf_path, 2)

    assert page_one_bytes != page_two_bytes


# --- Invalid/missing source ----------------------------------------------


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.pdf"

    with pytest.raises(FileNotFoundError):
        render_page_preview(missing_path, 1)


def test_directory_instead_of_file_raises_file_not_found(tmp_path: Path) -> None:
    directory_path = tmp_path / "a_directory"
    directory_path.mkdir()

    with pytest.raises(FileNotFoundError):
        render_page_preview(directory_path, 1)


def test_corrupt_file_raises_value_error_not_crash(tmp_path: Path) -> None:
    bad_path = tmp_path / "corrupt.pdf"
    bad_path.write_bytes(b"this is not a real pdf file")

    with pytest.raises(ValueError, match="Could not open"):
        render_page_preview(bad_path, 1)


def test_password_protected_file_raises_value_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "protected.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pdf_path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    doc.close()

    with pytest.raises(ValueError, match="password-protected"):
        render_page_preview(pdf_path, 1)


# --- Invalid page number ---------------------------------------------------


def test_page_number_zero_raises_value_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "single.pdf"
    _make_pdf(pdf_path, 1)

    with pytest.raises(ValueError, match="out of range"):
        render_page_preview(pdf_path, 0)


def test_negative_page_number_raises_value_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "single.pdf"
    _make_pdf(pdf_path, 1)

    with pytest.raises(ValueError, match="out of range"):
        render_page_preview(pdf_path, -1)


def test_page_number_beyond_last_page_raises_value_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "three_pages.pdf"
    _make_pdf(pdf_path, 3)

    with pytest.raises(ValueError, match="out of range"):
        render_page_preview(pdf_path, 4)


# --- Source immutability ----------------------------------------------------


def test_rendering_never_modifies_the_source_file(tmp_path: Path) -> None:
    pdf_path = tmp_path / "immutable.pdf"
    _make_pdf_with_text(pdf_path, "Do not touch this file")
    original_bytes = pdf_path.read_bytes()

    render_page_preview(pdf_path, 1)
    render_page_preview(pdf_path, 1, dpi=300)

    assert pdf_path.read_bytes() == original_bytes


def test_rendering_writes_no_temporary_files(tmp_path: Path) -> None:
    pdf_path = tmp_path / "no_temp_files.pdf"
    _make_pdf(pdf_path, 1)
    before = set(tmp_path.iterdir())

    render_page_preview(pdf_path, 1)

    after = set(tmp_path.iterdir())
    assert after == before
