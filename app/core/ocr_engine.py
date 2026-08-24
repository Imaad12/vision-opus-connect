"""OCR engine interface (OCR Phase 1).

An `OcrEngine` turns one already-rasterized page image into text plus
per-word positions and confidence — nothing more. It never opens a source
file, never decides what a value means, and never writes to the database;
`app.core.ocr_extraction` is the orchestrator that calls this, one page at
a time, and `app.core.import_extraction` (unchanged, reused as-is) is what
turns the resulting text into candidate quotation/BOQ fields.

`TesseractOcrEngine` is the only production implementation: local,
offline, no network call, matching this application's absolute no-cloud
constraint. `pytesseract`/`Pillow` are optional dependencies, imported
lazily so the rest of the application loads and runs normally even on a
machine where OCR has not been installed — `is_available()` reports that
honestly rather than the app crashing or silently pretending OCR ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OcrWord:
    """One recognized word and its position on the page, in pixels."""

    text: str
    left: int
    top: int
    width: int
    height: int
    line_key: tuple[int, int, int]  # (block_num, par_num, line_num) from the engine
    confidence: float | None  # 0-100, None if the engine didn't report one


@dataclass
class OcrPageResult:
    """Everything OCR found on one rasterized page. `failed=True` means the
    engine could not process this page at all (never a reason to invent
    text) — the page's other fields stay empty/default in that case."""

    page_number: int
    text: str = ""
    words: list[OcrWord] = field(default_factory=list)
    mean_confidence: float | None = None
    failed: bool = False
    warnings: list[str] = field(default_factory=list)


class OcrEngine(Protocol):
    name: str

    def is_available(self) -> bool:
        """Whether this engine can actually run right now (installed,
        loadable, and callable) — checked before any OCR is attempted, so
        an unavailable engine degrades to "OCR not run" rather than a
        crash partway through a document."""
        ...

    def ocr_image(self, image_bytes: bytes, *, page_number: int) -> OcrPageResult:
        """Run OCR on one page image (PNG bytes). Must never raise for an
        engine-level failure (bad image, engine crash, timeout) — such
        failures are reported as `OcrPageResult(failed=True, warnings=[...])`
        so one bad page can never take down the whole extraction."""
        ...


class TesseractOcrEngine:
    """Wraps `pytesseract` (which itself wraps the local Tesseract OCR
    binary). Both are optional dependencies — see `pyproject.toml`'s `ocr`
    extra — so importing this module never fails even when neither is
    installed; only calling it does, and only in the caught, reported way
    described above.
    """

    name = "tesseract"

    def is_available(self) -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            return True
        except Exception:  # noqa: BLE001 - "not available" covers every failure mode here
            return False

    def ocr_image(self, image_bytes: bytes, *, page_number: int) -> OcrPageResult:
        try:
            import io

            import pytesseract
            from PIL import Image
        except Exception as exc:  # noqa: BLE001
            return OcrPageResult(
                page_number=page_number,
                failed=True,
                warnings=[f"OCR engine is not available: {exc}"],
            )

        try:
            image = Image.open(io.BytesIO(image_bytes))
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except Exception as exc:  # noqa: BLE001 - a single bad/corrupt page must not abort the document
            return OcrPageResult(
                page_number=page_number,
                failed=True,
                warnings=[f"OCR failed on page {page_number}: {exc}"],
            )

        return _words_to_page_result(data, page_number=page_number)


def _words_to_page_result(data: dict, *, page_number: int) -> OcrPageResult:
    words: list[OcrWord] = []
    confidences: list[float] = []
    lines: dict[tuple[int, int, int], list[str]] = {}
    line_order: list[tuple[int, int, int]] = []

    count = len(data.get("text", []))
    for i in range(count):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            confidence = float(data.get("conf", ["-1"] * count)[i])
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence >= 0:
            confidences.append(confidence)

        line_key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        words.append(
            OcrWord(
                text=text,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                line_key=line_key,
                confidence=confidence if confidence >= 0 else None,
            )
        )
        if line_key not in lines:
            lines[line_key] = []
            line_order.append(line_key)
        lines[line_key].append(text)

    text = "\n".join(" ".join(lines[key]) for key in line_order)
    mean_confidence = (sum(confidences) / len(confidences)) if confidences else None
    return OcrPageResult(page_number=page_number, text=text, words=words, mean_confidence=mean_confidence)


def get_default_ocr_engine() -> OcrEngine:
    return TesseractOcrEngine()
