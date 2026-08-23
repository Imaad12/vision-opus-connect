"""PDF importer, via PyMuPDF.

Distinguishes text-based PDFs (extract text/tables) from scanned/image
PDFs (flag `requires_ocr` and stop — Phase 4 does not do OCR, and
absolutely does not call an external OCR/cloud service). Processes the
document page by page rather than loading everything into one structure
up front, per the Phase 4 performance guidance for large files.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.importers.base import BaseImporter, ExtractedTable, RawExtraction

# A page with fewer non-whitespace characters than this is treated as
# having no meaningful extractable text (i.e. likely a scanned image).
_MIN_CHARS_PER_PAGE_FOR_TEXT = 20


class PDFImporter(BaseImporter):
    extensions = ("pdf",)

    def extract(self, path: Path) -> RawExtraction:
        try:
            document = pymupdf.open(path)
        except Exception as exc:  # noqa: BLE001
            return RawExtraction(unsupported=True, unsupported_reason=f"Could not open PDF: {exc}")

        try:
            if document.needs_pass:
                # Phase 4 does not prompt for or store PDF passwords.
                return RawExtraction(
                    unsupported=True,
                    unsupported_reason="This PDF is password-protected. Remove the password and re-import.",
                )

            if document.page_count == 0:
                return RawExtraction(warnings=["This PDF has no pages."])

            text_parts: list[str] = []
            tables: list[ExtractedTable] = []
            warnings: list[str] = []
            total_chars = 0

            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                page_text = page.get_text().strip()
                total_chars += len(page_text)
                if page_text:
                    text_parts.append(page_text)

                try:
                    found_tables = page.find_tables()
                    for table_index, table in enumerate(found_tables.tables):
                        rows = table.extract()
                        cleaned_rows = [
                            ["" if cell is None else str(cell) for cell in row] for row in rows
                        ]
                        if cleaned_rows:
                            tables.append(
                                ExtractedTable(
                                    name=f"page {page_index + 1} table {table_index + 1}",
                                    rows=cleaned_rows,
                                )
                            )
                except Exception as exc:  # noqa: BLE001 - table detection is best-effort
                    warnings.append(f"Could not detect tables on page {page_index + 1}: {exc}")

            average_chars_per_page = total_chars / document.page_count
            if average_chars_per_page < _MIN_CHARS_PER_PAGE_FOR_TEXT:
                return RawExtraction(
                    requires_ocr=True,
                    warnings=[
                        "This PDF has little or no extractable text — it appears to be a scanned "
                        "or image-based document. OCR is required before this can be reviewed as "
                        "quotation/BOQ data."
                    ],
                )

            return RawExtraction(text="\n\n".join(text_parts), tables=tables, warnings=warnings)
        finally:
            document.close()
