from app.core.ocr_engine import TesseractOcrEngine, _words_to_page_result, get_default_ocr_engine


def test_tesseract_engine_reports_unavailable_when_dependencies_missing() -> None:
    """This sandbox genuinely has neither `pytesseract` nor the Tesseract
    binary installed -- `is_available()` must say so cleanly rather than
    raising, so the rest of the application can degrade to OCR_REQUIRED
    instead of crashing."""
    engine = TesseractOcrEngine()
    assert engine.is_available() is False


def test_tesseract_engine_ocr_image_fails_safely_when_dependencies_missing() -> None:
    engine = TesseractOcrEngine()
    result = engine.ocr_image(b"not a real image", page_number=1)
    assert result.failed is True
    assert result.page_number == 1
    assert result.text == ""
    assert result.warnings


def test_get_default_ocr_engine_returns_tesseract_engine() -> None:
    assert isinstance(get_default_ocr_engine(), TesseractOcrEngine)


def test_words_to_page_result_groups_words_into_lines_and_averages_confidence() -> None:
    # Shaped exactly like `pytesseract.image_to_data(..., output_type=DICT)`.
    data = {
        "text": ["Quotation", "Number:", "Q-1", "", "Net", "Amount:", "100.00"],
        "left": [10, 90, 160, 0, 10, 40, 100],
        "top": [10, 10, 10, 0, 40, 40, 40],
        "width": [70, 60, 30, 0, 30, 60, 60],
        "height": [15, 15, 15, 0, 15, 15, 15],
        "conf": ["95", "92", "40", "-1", "88", "90", "97"],
        "block_num": [1, 1, 1, 1, 1, 1, 1],
        "par_num": [1, 1, 1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 1, 2, 2, 2],
    }

    result = _words_to_page_result(data, page_number=3)

    assert result.page_number == 3
    assert result.failed is False
    assert "Quotation Number: Q-1" in result.text
    assert "Net Amount: 100.00" in result.text
    assert result.text.count("\n") == 1  # two lines
    # Empty-text entries are skipped entirely (never a phantom word).
    assert all(word.text for word in result.words)
    assert len(result.words) == 6
    # Mean of the reported confidences (the -1 entry is excluded).
    assert result.mean_confidence == sum([95, 92, 40, 88, 90, 97]) / 6
