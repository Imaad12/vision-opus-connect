"""OCR extraction orchestrator (OCR Phase 1).

Turns a scanned PDF or image file into a `RawExtraction` — the exact same
dataclass every other importer already produces (see `app.importers.base`)
— so nothing downstream (`app.core.import_extraction.extract_candidates`,
staging, matching, review, confirmation) needs to know or care that OCR
was involved. This module owns exactly three things: rasterizing pages,
calling an `OcrEngine` on each one, and reassembling the results — it
never interprets what the text *means* (that stays `import_extraction`'s
job) and never touches the database.

Every failure mode is caught and turned into a `RawExtraction` state that
already exists in this application (`unsupported`, `requires_ocr`, or a
lower-confidence/warned normal result) rather than propagating an
exception — `app.services.import_service.run_extraction` already has a
single try/except around the whole extraction step as a last resort, but
OCR failures are common enough (a bad scan, a missing engine, a corrupt
page) that they are handled here explicitly, page by page, so that one
unreadable page never discards the rest of a multi-page document.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.core.document_preview import rasterize_page_to_png
from app.core.ocr_engine import OcrEngine, OcrPageResult, get_default_ocr_engine
from app.core.ocr_table_reconstruction import reconstruct_table_from_words
from app.importers.base import RawExtraction

# Matches PDFImporter's own threshold for "this page has no meaningful
# text" -- reused here as the signal for "OCR found essentially nothing on
# this page" (e.g. a blank page, or a drawing/attachment with no text).
_MIN_CHARS_FOR_USEFUL_TEXT = 20

# Rendering at a higher DPI than the source screen resolution measurably
# improves OCR accuracy on typical office-scanner output without making
# pages unreasonably large to process. This is also the fallback used
# whenever a page's real native resolution can't be measured (see
# `_effective_render_dpi`) -- unchanged from every version of this module
# before the DPI fix below, so a page that can't be measured renders
# exactly as it always has.
_RENDER_DPI = 300

# Bounds for `_effective_render_dpi`'s per-page DPI: never render below
# 150 (a genuinely low-resolution scan still gets a reasonable working
# resolution for OCR, not literally its raw pixel count), never above the
# previous fixed default of 300 (bounds worst-case cost at today's level;
# a page whose native resolution is >=300 DPI renders at exactly the same
# 300 DPI it always has).
_MIN_RENDER_DPI = 150
_MAX_RENDER_DPI = 300


def _effective_render_dpi(document: pymupdf.Document, page: pymupdf.Page) -> int:
    """The DPI to rasterize `page` at for OCR, derived from its own
    dominant embedded image's native pixel resolution rather than the
    fixed `_RENDER_DPI` constant.

    Real archive scans were measured to declare a `MediaBox` far larger
    than their embedded image's actual pixel resolution (e.g. a page
    sized "26.5 x 41.5 inches" wrapping a 1910x2986px image) -- a
    "1 point = 1 native pixel" (72 DPI) mis-scaling artifact of the
    scan-to-PDF software that produced them. Rendering those pages at a
    fixed 300 DPI against the inflated MediaBox produced ~10x more pixels
    than the source actually contains, which the OCR engine then had to
    process for no accuracy gain (measured: 8.9x-10x slower across 3 real
    sampled pages, with no accuracy loss from rendering at the resolution
    computed here instead).

    On a normally-scaled PDF (native resolution >= 300 DPI, the common
    case), this reproduces `_RENDER_DPI` exactly -- confirmed by
    construction, since the result is clamped to `_MAX_RENDER_DPI ==
    _RENDER_DPI`. Falls back to `_RENDER_DPI` unchanged whenever there is
    no embedded image to measure, or on any error reading one.
    """
    try:
        images = page.get_images(full=True)
        if not images:
            return _RENDER_DPI

        # The *dominant* image (most native pixels) sets the DPI -- a page
        # can carry a small embedded logo/stamp alongside its main scanned
        # content, and that must not be what determines render resolution.
        best_pixels = 0
        native_width = native_height = 0
        for image_info in images:
            xref = image_info[0]
            info = document.extract_image(xref)
            width, height = info.get("width", 0), info.get("height", 0)
            pixels = width * height
            if pixels > best_pixels:
                best_pixels, native_width, native_height = pixels, width, height

        if best_pixels == 0:
            return _RENDER_DPI

        width_pt, height_pt = page.rect.width, page.rect.height
        if width_pt <= 0 or height_pt <= 0:
            return _RENDER_DPI

        # Isotropic DPI (pymupdf renders at one DPI for both axes) -- take
        # the smaller of the two axis-derived values so neither axis is
        # ever rendered above what the source actually contains.
        dpi_x = native_width / (width_pt / 72.0)
        dpi_y = native_height / (height_pt / 72.0)
        native_dpi = min(dpi_x, dpi_y)

        return int(max(_MIN_RENDER_DPI, min(_MAX_RENDER_DPI, round(native_dpi))))
    except Exception:  # noqa: BLE001 - any measurement failure falls back to the
        # previous, always-safe fixed default rather than guessing.
        return _RENDER_DPI


def extract_via_ocr(path: Path, *, engine: OcrEngine | None = None) -> RawExtraction:
    engine = engine or get_default_ocr_engine()

    if not engine.is_available():
        return RawExtraction(
            requires_ocr=True,
            warnings=[
                "OCR is enabled but the OCR engine is not available on this machine "
                "(it may not be installed). This document is staged for manual review."
            ],
        )

    try:
        document = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001
        return RawExtraction(unsupported=True, unsupported_reason=f"Could not open document for OCR: {exc}")

    try:
        if document.needs_pass:
            return RawExtraction(
                unsupported=True,
                unsupported_reason="This document is password-protected. Remove the password and re-import.",
            )
        if document.page_count == 0:
            return RawExtraction(warnings=["This document has no pages."])

        text_parts: list[str] = []
        tables = []
        warnings: list[str] = []
        ocr_pages: list[dict] = []
        any_page_succeeded = False

        for page_index in range(document.page_count):
            page_number = page_index + 1
            try:
                page = document.load_page(page_index)
                render_dpi = _effective_render_dpi(document, page)
                image_bytes = rasterize_page_to_png(page, dpi=render_dpi)
            except Exception as exc:  # noqa: BLE001 - one bad page must not abort the document
                warnings.append(f"Page {page_number}: could not be rendered for OCR ({exc}).")
                ocr_pages.append(
                    {"page_number": page_number, "char_count": 0, "mean_confidence": None, "failed": True}
                )
                continue

            try:
                result: OcrPageResult = engine.ocr_image(image_bytes, page_number=page_number)
            except Exception as exc:  # noqa: BLE001 - defense in depth: an engine must not raise, but
                # this orchestrator never trusts that promise on the caller's behalf.
                warnings.append(f"Page {page_number}: OCR engine raised an unexpected error ({exc}).")
                ocr_pages.append(
                    {"page_number": page_number, "char_count": 0, "mean_confidence": None, "failed": True}
                )
                continue
            ocr_pages.append(
                {
                    "page_number": page_number,
                    "char_count": len(result.text),
                    "mean_confidence": result.mean_confidence,
                    "failed": result.failed,
                }
            )

            if result.failed:
                warnings.extend(result.warnings or [f"Page {page_number}: OCR failed."])
                continue

            any_page_succeeded = True
            if len(result.text.strip()) < _MIN_CHARS_FOR_USEFUL_TEXT:
                warnings.append(
                    f"Page {page_number}: OCR found little or no usable text "
                    "(this may be a blank page, drawing, or attachment)."
                )

            text_parts.append(f"--- Page {page_number} ---\n{result.text}")

            table = reconstruct_table_from_words(result.words, page_number=page_number)
            if table is not None:
                tables.append(table)
            elif _looks_like_it_has_a_table(result.text):
                warnings.append(
                    f"Page {page_number}: a table-like region was found but its column "
                    "structure could not be reliably identified from the scan. Add or "
                    "correct BOQ lines manually for this page."
                )

        if not any_page_succeeded:
            warnings.append("OCR could not read any page of this document.")

        return RawExtraction(
            text="\n\n".join(text_parts) if text_parts else None,
            tables=tables,
            warnings=warnings,
            ocr_pages=ocr_pages,
        )
    finally:
        document.close()


def _looks_like_it_has_a_table(text: str) -> bool:
    """Cheap heuristic used only to decide whether an "uncertain BOQ
    structure" warning is worth showing: does this page's OCR text contain
    more than one of the column header keywords `extract_boq_rows` already
    looks for? If so, there was probably a table here that the column
    reconstruction just couldn't confidently reassemble."""
    lowered = text.lower()
    keywords = ("description", "quantity", "qty", "unit rate", "amount", "item")
    return sum(1 for keyword in keywords if keyword in lowered) >= 2
