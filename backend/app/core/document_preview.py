"""Reusable page-preview rendering.

This is the one place a source document's page is rasterized into an
image for a *human* to look at — first consumer is the eventual Review
Queue UI (a reviewer needs to see the actual scan next to the extracted
fields), but it is deliberately generic: any future caller that needs
"show me page N of this document" reuses this, rather than each one
reimplementing PyMuPDF calls.

Read-only: `render_page_preview` only ever opens `path` for reading and
never writes to, moves, renames, or otherwise modifies it — the same
source-document-immutability guarantee already made everywhere else in
this codebase (see `app.services.import_service`).

`rasterize_page_to_png` is the exact rendering primitive
`app.core.ocr_extraction.extract_via_ocr` already used inline
(`page.get_pixmap(dpi=...).tobytes("png")`) — factored out here so there
is exactly one implementation of "turn a PyMuPDF page into PNG bytes",
shared by OCR and by this module, rather than two copies that could drift
apart. DPI *selection* is a separate concern deliberately left to each
caller: OCR derives an adaptive per-page DPI for recognition accuracy
(`ocr_extraction._effective_render_dpi`), while a human-facing preview
just wants a caller-supplied, reasonable-for-on-screen-viewing DPI — this
module does not decide that for OCR, and does not adopt OCR's heuristic
for itself.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf


def rasterize_page_to_png(page: pymupdf.Page, *, dpi: int) -> bytes:
    """Render one already-loaded PyMuPDF page to PNG bytes at `dpi`. The
    exact two-call sequence (`get_pixmap` then `tobytes("png")`)
    `ocr_extraction.py` used inline before this module existed."""
    pixmap = page.get_pixmap(dpi=dpi)
    return pixmap.tobytes("png")


def render_page_preview(path: Path, page_number: int, *, dpi: int = 150) -> bytes:
    """Render `page_number` (1-based) of the PDF at `path` to PNG bytes for
    display, at `dpi`. Opens `path` read-only; never modifies it, never
    writes a temporary file (`pymupdf` rasterizes directly into memory).

    Raises `FileNotFoundError` if `path` does not exist or is not a
    regular file. Raises `ValueError` if the file cannot be opened as a
    document (corrupted, unsupported format, or password-protected), or
    if `page_number` is out of range for it — mirrors the same failure
    modes `app.core.ocr_extraction.extract_via_ocr` already recognizes
    for a PDF, just raised rather than folded into a `RawExtraction`
    sentinel, since this is a direct, on-demand rendering call rather
    than a pipeline step that must always produce *some* result.
    """
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")

    try:
        document = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001 - pymupdf's own exception types for a corrupt/unsupported file
        raise ValueError(f"Could not open '{path.name}' as a document: {exc}") from exc

    try:
        if document.needs_pass:
            raise ValueError(f"'{path.name}' is password-protected and cannot be previewed.")
        if document.page_count == 0:
            raise ValueError(f"'{path.name}' has no pages to preview.")
        if page_number < 1 or page_number > document.page_count:
            raise ValueError(
                f"Page {page_number} is out of range for '{path.name}' "
                f"({document.page_count} page(s))."
            )
        page = document.load_page(page_number - 1)
        return rasterize_page_to_png(page, dpi=dpi)
    finally:
        document.close()


def get_page_count(path: Path) -> int:
    """How many pages `path` has, for a caller building a pager ("page N
    of M") that doesn't need every page rasterized just to know the
    total. Same open/validate/close discipline and failure modes as
    `render_page_preview` (`FileNotFoundError`/`ValueError`), deliberately
    not implemented as `len(list(render every page))` -- opening the
    document once is far cheaper than rendering it."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")

    try:
        document = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001 - pymupdf's own exception types for a corrupt/unsupported file
        raise ValueError(f"Could not open '{path.name}' as a document: {exc}") from exc

    try:
        if document.needs_pass:
            raise ValueError(f"'{path.name}' is password-protected and cannot be previewed.")
        return document.page_count
    finally:
        document.close()
