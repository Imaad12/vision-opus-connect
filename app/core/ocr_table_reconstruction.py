"""Best-effort reconstruction of a table's rows/columns from OCR word
positions (OCR Phase 1).

A scanned page has no vector table structure the way a text-layer PDF
does (`PDFImporter` finds tables via `pymupdf`'s `find_tables()`, which
depends on that vector structure and cannot see a raster image at all).
OCR only gives us words and their pixel positions, so a BOQ table has to
be reassembled from those positions before it can be handed to the
*existing, unmodified* `app.core.import_extraction.extract_boq_rows`
(which already knows how to find a header row and map columns by
keyword — reused here, not duplicated).

The heuristic is deliberately simple and conservative: split each OCR
text line into cells at unusually large horizontal gaps between words. If
the resulting rows don't look consistent enough to be a real table (too
few multi-cell rows, or wildly inconsistent cell counts), this returns
`None` rather than guessing — per the brief, "if table structure is
uncertain, mark the BOQ as requiring review" rather than silently
fabricating misaligned columns.
"""

from __future__ import annotations

from statistics import median

from app.core.ocr_engine import OcrWord
from app.importers.base import ExtractedTable

# A gap between two words on the same line wider than this multiple of the
# median word width on the page is treated as a column boundary rather
# than normal word spacing.
_COLUMN_GAP_WIDTH_MULTIPLE = 2.5
_MIN_COLUMN_GAP_PIXELS = 15

# At least this fraction of a page's reconstructed lines must agree on the
# (non-trivial) cell count for the page to be treated as a real table at
# all; otherwise the layout is too inconsistent to trust.
_MIN_CONSISTENT_ROW_FRACTION = 0.5
_MIN_ROWS_FOR_A_TABLE = 3
_MIN_COLUMNS_FOR_A_TABLE = 2


def _group_lines(words: list[OcrWord]) -> list[list[OcrWord]]:
    lines: dict[tuple[int, int, int], list[OcrWord]] = {}
    order: list[tuple[int, int, int]] = []
    for word in words:
        if word.line_key not in lines:
            lines[word.line_key] = []
            order.append(word.line_key)
        lines[word.line_key].append(word)

    grouped = []
    for key in order:
        line_words = sorted(lines[key], key=lambda w: w.left)
        grouped.append(line_words)
    # Reading order: top-to-bottom by the line's topmost word.
    grouped.sort(key=lambda line: min(w.top for w in line))
    return grouped


def _split_line_into_cells(line: list[OcrWord], gap_threshold: float) -> list[str]:
    cells: list[list[str]] = [[line[0].text]]
    for previous, current in zip(line, line[1:]):
        gap = current.left - (previous.left + previous.width)
        if gap > gap_threshold:
            cells.append([current.text])
        else:
            cells[-1].append(current.text)
    return [" ".join(cell) for cell in cells]


def reconstruct_table_from_words(words: list[OcrWord], *, page_number: int) -> ExtractedTable | None:
    """Attempt to turn one page's OCR words into a grid table. Returns
    `None` (never a guessed/misaligned table) when the layout isn't
    confidently table-shaped."""
    if not words:
        return None

    widths = [w.width for w in words if w.width > 0]
    if not widths:
        return None
    gap_threshold = max(_MIN_COLUMN_GAP_PIXELS, median(widths) * _COLUMN_GAP_WIDTH_MULTIPLE)

    lines = _group_lines(words)
    if len(lines) < _MIN_ROWS_FOR_A_TABLE:
        return None

    rows = [_split_line_into_cells(line, gap_threshold) for line in lines]
    cell_counts = [len(row) for row in rows]

    multi_cell_counts = [c for c in cell_counts if c >= _MIN_COLUMNS_FOR_A_TABLE]
    if len(multi_cell_counts) < _MIN_ROWS_FOR_A_TABLE:
        # Almost nothing split into more than one cell -- this page reads
        # as plain paragraphs/labels, not a table.
        return None

    modal_count = max(set(multi_cell_counts), key=multi_cell_counts.count)
    agreeing = sum(1 for c in cell_counts if c == modal_count)
    if agreeing / len(rows) < _MIN_CONSISTENT_ROW_FRACTION:
        # Cell counts vary too much row-to-row to trust the column
        # boundaries this heuristic guessed.
        return None

    return ExtractedTable(name=f"page {page_number} (OCR)", rows=rows)
