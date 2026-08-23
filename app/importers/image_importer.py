"""Image importer: .png/.jpg/.jpeg/.tif/.tiff.

Images carry no machine-readable text without OCR, and Phase 4 explicitly
excludes OCR (no external/cloud OCR calls, no bundled OCR engine). Every
image is therefore always marked `requires_ocr` — this importer exists so
image files are still recognized and staged (rather than falling through
to "unsupported file type"), consistent with how a scanned PDF is handled.
"""

from __future__ import annotations

from pathlib import Path

from app.importers.base import BaseImporter, RawExtraction


class ImageImporter(BaseImporter):
    extensions = ("png", "jpg", "jpeg", "tif", "tiff")

    def extract(self, path: Path) -> RawExtraction:
        return RawExtraction(
            requires_ocr=True,
            warnings=[
                "Image files require OCR to extract text, which is not implemented in Phase 4. "
                "This document is staged for manual review."
            ],
        )
