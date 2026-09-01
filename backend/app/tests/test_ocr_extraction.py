"""Tests for `app.core.ocr_extraction.extract_via_ocr` -- the orchestrator
that rasterizes pages (via the real `pymupdf`, exactly as `PDFImporter`
already does) and calls an injected `OcrEngine`.

A `FakeOcrEngine` stands in for Tesseract throughout (Tesseract/pytesseract
are not installed in this environment -- see `test_ocr_engine.py`, which
proves the real `TesseractOcrEngine` degrades to `is_available() ==
False` rather than crashing). Standing the fake in at the `OcrEngine`
boundary keeps these tests deterministic and fast while still exercising
the real page-rendering and result-aggregation code paths.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image

from app.core.ocr_engine import OcrPageResult, OcrWord
from app.core.ocr_extraction import _effective_render_dpi, extract_via_ocr


class FakeOcrEngine:
    name = "fake"

    def __init__(self, page_results: dict[int, OcrPageResult] | None = None, *, available: bool = True) -> None:
        self._page_results = page_results or {}
        self._available = available
        self.calls: list[int] = []

    def is_available(self) -> bool:
        return self._available

    def ocr_image(self, image_bytes: bytes, *, page_number: int) -> OcrPageResult:
        self.calls.append(page_number)
        if page_number in self._page_results:
            return self._page_results[page_number]
        return OcrPageResult(page_number=page_number, text="")


def _make_pdf(path: Path, page_count: int) -> None:
    doc = pymupdf.open()
    for _ in range(page_count):
        doc.new_page()
    doc.save(path)
    doc.close()


def _text_result(page_number: int, text: str, confidence: float = 92.0) -> OcrPageResult:
    return OcrPageResult(page_number=page_number, text=text, mean_confidence=confidence)


def _make_scanned_pdf(path: Path, *, mediabox_pt: tuple[float, float], image_px: tuple[int, int]) -> None:
    """A single-page PDF whose page size is `mediabox_pt` (points) and
    whose sole content is one embedded raster image of `image_px` native
    pixels -- the same shape as a real scan-to-PDF page, used to test
    `_effective_render_dpi` against a controlled, known resolution instead
    of the real archive files (not available in this environment)."""
    image = Image.new("RGB", image_px, "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=mediabox_pt[0], height=mediabox_pt[1])
    page.insert_image(page.rect, stream=buffer.getvalue())
    doc.save(path)
    doc.close()


def _png_size(image_bytes: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(image_bytes)).size


# --- Per-page render DPI (real-archive DPI/rasterization fix) ---------------


def test_effective_render_dpi_matches_fixed_default_for_a_normally_scaled_scan(tmp_path: Path) -> None:
    # A standard US-Letter page (8.5 x 11 in) wrapping a native 300 DPI
    # scan (2550 x 3300 px) -- the common, non-anomalous case. The
    # computed DPI must equal the previous fixed constant exactly, so a
    # normal scan renders byte-for-byte as it always has.
    pdf_path = tmp_path / "normal_scan.pdf"
    _make_scanned_pdf(pdf_path, mediabox_pt=(612.0, 792.0), image_px=(2550, 3300))
    doc = pymupdf.open(pdf_path)
    try:
        assert _effective_render_dpi(doc, doc.load_page(0)) == 300
    finally:
        doc.close()


def test_effective_render_dpi_is_reduced_for_a_mediabox_that_does_not_match_native_resolution(
    tmp_path: Path,
) -> None:
    # Reproduces the real archive's measured anomaly: a MediaBox declared
    # far larger (26.5 x 41.5 "inches") than the embedded image's actual
    # native resolution (1910 x 2986 px) -- a ~72 DPI scan wrapped in an
    # inflated page size. The computed DPI must be far below the fixed
    # 300 default (it must not render ~10x more pixels than the source
    # contains), and never below the configured floor.
    pdf_path = tmp_path / "anomalous_mediabox.pdf"
    _make_scanned_pdf(pdf_path, mediabox_pt=(26.5 * 72, 41.5 * 72), image_px=(1910, 2986))
    doc = pymupdf.open(pdf_path)
    try:
        dpi = _effective_render_dpi(doc, doc.load_page(0))
        # True native resolution here is ~72 DPI (1910px / 26.5in); the
        # floor keeps this from degrading further, so the result clamps
        # to exactly the floor rather than the true (too-low) native value.
        assert dpi == 150
        assert dpi < 300
    finally:
        doc.close()


def test_effective_render_dpi_falls_back_to_default_with_no_embedded_image(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank_page.pdf"
    _make_pdf(pdf_path, 1)
    doc = pymupdf.open(pdf_path)
    try:
        assert _effective_render_dpi(doc, doc.load_page(0)) == 300
    finally:
        doc.close()


def test_effective_render_dpi_never_exceeds_the_previous_fixed_default(tmp_path: Path) -> None:
    # A native resolution *higher* than 300 DPI must still clamp to 300 --
    # this fix must never make OCR slower than the old fixed behaviour.
    pdf_path = tmp_path / "very_high_res.pdf"
    _make_scanned_pdf(pdf_path, mediabox_pt=(612.0, 792.0), image_px=(5100, 6600))  # 600 DPI native
    doc = pymupdf.open(pdf_path)
    try:
        assert _effective_render_dpi(doc, doc.load_page(0)) == 300
    finally:
        doc.close()


def test_extract_via_ocr_renders_anomalous_scan_at_reduced_resolution(tmp_path: Path) -> None:
    pdf_path = tmp_path / "anomalous.pdf"
    _make_scanned_pdf(pdf_path, mediabox_pt=(26.5 * 72, 41.5 * 72), image_px=(1910, 2986))

    captured: dict[int, bytes] = {}

    class CapturingEngine(FakeOcrEngine):
        def ocr_image(self, image_bytes: bytes, *, page_number: int) -> OcrPageResult:
            captured[page_number] = image_bytes
            return super().ocr_image(image_bytes, page_number=page_number)

    engine = CapturingEngine({1: _text_result(1, "Quotation Number: Q-DPI\n")})
    result = extract_via_ocr(pdf_path, engine=engine)

    assert "Q-DPI" in (result.text or "")
    width, height = _png_size(captured[1])
    # At the old fixed 300 DPI this page would render at roughly
    # 26.5*300 x 41.5*300 = 7950x12450px (~10x the pixels this source
    # actually contains). At the floor-clamped 150 DPI the fix computes
    # here, it renders at ~3975x6225px instead -- far fewer pixels for
    # the OCR engine to process, while still at least matching (not
    # degrading below) the image's own native resolution.
    assert width < 4200
    assert height < 6500


def test_extract_via_ocr_renders_normal_scan_unchanged(tmp_path: Path) -> None:
    pdf_path = tmp_path / "normal.pdf"
    _make_scanned_pdf(pdf_path, mediabox_pt=(612.0, 792.0), image_px=(2550, 3300))

    captured: dict[int, bytes] = {}

    class CapturingEngine(FakeOcrEngine):
        def ocr_image(self, image_bytes: bytes, *, page_number: int) -> OcrPageResult:
            captured[page_number] = image_bytes
            return super().ocr_image(image_bytes, page_number=page_number)

    engine = CapturingEngine({1: _text_result(1, "Quotation Number: Q-NORMAL\n")})
    result = extract_via_ocr(pdf_path, engine=engine)

    assert "Q-NORMAL" in (result.text or "")
    width, height = _png_size(captured[1])
    assert (width, height) == (2550, 3300)


# --- Engine / document availability -----------------------------------------


def test_engine_unavailable_stages_as_ocr_required(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    _make_pdf(pdf_path, 1)

    result = extract_via_ocr(pdf_path, engine=FakeOcrEngine(available=False))

    assert result.requires_ocr is True
    assert result.unsupported is False
    assert result.text is None


def test_corrupt_file_is_reported_as_unsupported_not_crashed(tmp_path: Path) -> None:
    bad_path = tmp_path / "corrupt.pdf"
    bad_path.write_bytes(b"this is not a real pdf file")

    result = extract_via_ocr(bad_path, engine=FakeOcrEngine())

    assert result.unsupported is True
    assert result.unsupported_reason


def test_zero_page_document_is_handled(tmp_path: Path) -> None:
    # PyMuPDF refuses to save a real zero-page PDF ("cannot save with zero
    # pages"), so there is no genuine on-disk fixture for this edge case --
    # mocked the same way `test_pdf_importer.py` handles it, to exercise
    # the `page_count == 0` guard deterministically.
    from unittest.mock import MagicMock

    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(b"placeholder")

    fake_document = MagicMock()
    fake_document.needs_pass = False
    fake_document.page_count = 0

    with patch("app.core.ocr_extraction.pymupdf.open", return_value=fake_document):
        result = extract_via_ocr(pdf_path, engine=FakeOcrEngine())

    assert result.unsupported is False
    assert result.requires_ocr is False
    assert "no pages" in " ".join(result.warnings).lower()


# --- Successful / partial / empty OCR ---------------------------------------


def test_clean_single_page_ocr_produces_usable_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "clean.pdf"
    _make_pdf(pdf_path, 1)
    engine = FakeOcrEngine(
        {
            1: _text_result(
                1,
                "Quotation Number: VN/QU/412/18\nQuotation Date: 21/11/2018\nNet Amount: 168,495.00\n",
            )
        }
    )

    result = extract_via_ocr(pdf_path, engine=engine)

    assert result.unsupported is False
    assert result.requires_ocr is False
    assert "VN/QU/412/18" in (result.text or "")
    assert result.ocr_pages == [{"page_number": 1, "char_count": len(engine._page_results[1].text), "mean_confidence": 92.0, "failed": False}]


def test_empty_ocr_output_produces_no_text_but_does_not_crash(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank_scan.pdf"
    _make_pdf(pdf_path, 1)
    engine = FakeOcrEngine({1: OcrPageResult(page_number=1, text="")})

    result = extract_via_ocr(pdf_path, engine=engine)

    assert result.unsupported is False
    assert result.requires_ocr is False
    # No page produced usable text; nothing is guessed.
    assert (result.text or "").strip().replace("--- Page 1 ---", "").strip() == ""
    assert any("little or no usable text" in w for w in result.warnings)


def test_partial_ocr_success_keeps_the_pages_that_worked(tmp_path: Path) -> None:
    pdf_path = tmp_path / "partial.pdf"
    _make_pdf(pdf_path, 2)
    engine = FakeOcrEngine(
        {
            1: _text_result(1, "Quotation Number: Q-100\nQuotation Date: 01/01/2024\n"),
            2: OcrPageResult(page_number=2, text="", failed=True, warnings=["Page 2: OCR failed."]),
        }
    )

    result = extract_via_ocr(pdf_path, engine=engine)

    assert "Q-100" in (result.text or "")
    assert any("Page 2" in w for w in result.warnings)
    assert result.ocr_pages[0]["failed"] is False
    assert result.ocr_pages[1]["failed"] is True


def test_engine_failure_on_every_page_stages_safely_with_no_fabricated_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "unreadable.pdf"
    _make_pdf(pdf_path, 2)
    engine = FakeOcrEngine(
        {
            1: OcrPageResult(page_number=1, text="", failed=True, warnings=["Page 1: OCR failed."]),
            2: OcrPageResult(page_number=2, text="", failed=True, warnings=["Page 2: OCR failed."]),
        }
    )

    result = extract_via_ocr(pdf_path, engine=engine)

    assert result.unsupported is False
    assert result.text is None
    assert any("could not read any page" in w.lower() for w in result.warnings)
    assert all(page["failed"] for page in result.ocr_pages)


def test_engine_raising_unexpectedly_on_one_page_does_not_abort_the_document(tmp_path: Path) -> None:
    """Defense in depth: an `OcrEngine` implementation is documented to
    never raise, but the orchestrator must not trust that on the caller's
    behalf -- a rogue/unexpected exception from one page must degrade to a
    failed page, never crash `run_extraction`."""
    pdf_path = tmp_path / "flaky_engine.pdf"
    _make_pdf(pdf_path, 2)

    class RaisingOnPageTwoEngine(FakeOcrEngine):
        def ocr_image(self, image_bytes: bytes, *, page_number: int) -> OcrPageResult:
            if page_number == 2:
                raise RuntimeError("engine crashed")
            return super().ocr_image(image_bytes, page_number=page_number)

    engine = RaisingOnPageTwoEngine({1: _text_result(1, "Quotation Number: Q-200\n")})

    result = extract_via_ocr(pdf_path, engine=engine)

    assert "Q-200" in (result.text or "")
    assert any("page 2" in w.lower() and "unexpected" in w.lower() for w in result.warnings)
    assert result.ocr_pages[1]["failed"] is True


def test_page_rendering_failure_does_not_abort_the_document(tmp_path: Path) -> None:
    pdf_path = tmp_path / "render_failure.pdf"
    _make_pdf(pdf_path, 2)
    engine = FakeOcrEngine({2: _text_result(2, "Quotation Number: Q-300\n")})

    real_get_pixmap = pymupdf.Page.get_pixmap

    def _flaky_get_pixmap(self, *args, **kwargs):
        if self.number == 0:
            raise RuntimeError("simulated rendering failure")
        return real_get_pixmap(self, *args, **kwargs)

    with patch.object(pymupdf.Page, "get_pixmap", _flaky_get_pixmap):
        result = extract_via_ocr(pdf_path, engine=engine)

    assert "Q-300" in (result.text or "")
    assert any("could not be rendered" in w for w in result.warnings)
    assert result.ocr_pages[0]["failed"] is True
    assert engine.calls == [2]  # page 1 was never handed to the engine at all


# --- BOQ table reconstruction integration -----------------------------------


def test_boq_shaped_ocr_words_become_a_table(tmp_path: Path) -> None:
    pdf_path = tmp_path / "boq.pdf"
    _make_pdf(pdf_path, 1)

    columns = [0, 300, 600, 900, 1200, 1500]

    def _row_words(row_index: int, cells: list[str]) -> list[OcrWord]:
        return [
            OcrWord(text=cell, left=columns[i], top=row_index * 30, width=50, height=20, line_key=(1, 1, row_index), confidence=90.0)
            for i, cell in enumerate(cells)
        ]

    words: list[OcrWord] = []
    words += _row_words(0, ["Item", "Description", "Qty", "Unit", "Rate", "Amount"])
    words += _row_words(1, ["1", "Excavation", "10", "m3", "50.00", "500.00"])
    words += _row_words(2, ["2", "Blockwork", "200", "m2", "75.00", "15000.00"])
    words += _row_words(3, ["3", "Reinforcement", "5", "ton", "3000.00", "15000.00"])

    engine = FakeOcrEngine({1: OcrPageResult(page_number=1, text="Bill of Quantities", words=words, mean_confidence=90.0)})

    result = extract_via_ocr(pdf_path, engine=engine)

    assert len(result.tables) == 1
    assert result.tables[0].rows[0] == ["Item", "Description", "Qty", "Unit", "Rate", "Amount"]


def test_ambiguous_boq_layout_is_flagged_not_guessed(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ambiguous_boq.pdf"
    _make_pdf(pdf_path, 1)

    # Contains BOQ-like keywords but no reliable column layout (all one
    # run-on line) -- table reconstruction must decline, and a warning
    # must explain why, rather than silently emitting misaligned rows.
    text = "Item Description Qty Unit Rate Amount 1 Excavation works ten cubic meters fifty per unit"
    words = [
        OcrWord(text=token, left=i * 40, top=0, width=35, height=20, line_key=(1, 1, 0), confidence=80.0)
        for i, token in enumerate(text.split())
    ]
    engine = FakeOcrEngine({1: OcrPageResult(page_number=1, text=text, words=words, mean_confidence=80.0)})

    result = extract_via_ocr(pdf_path, engine=engine)

    assert result.tables == []
    assert any("could not be reliably identified" in w for w in result.warnings)


# --- Multi-page aggregation --------------------------------------------------


def test_multi_page_document_preserves_page_boundaries_and_metadata(tmp_path: Path) -> None:
    pdf_path = tmp_path / "multipage.pdf"
    _make_pdf(pdf_path, 3)
    engine = FakeOcrEngine(
        {
            1: _text_result(1, "Quotation Number: Q-1\n"),
            2: _text_result(2, "Continuation page with scope of work.\n"),
            3: _text_result(3, "Net Amount: 100,000.00\n"),
        }
    )

    result = extract_via_ocr(pdf_path, engine=engine)

    assert len(result.ocr_pages) == 3
    assert [p["page_number"] for p in result.ocr_pages] == [1, 2, 3]
    assert "Q-1" in (result.text or "")
    assert "100,000.00" in (result.text or "")
    assert "--- Page 2 ---" in (result.text or "")
