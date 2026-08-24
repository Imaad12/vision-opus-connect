from app.core.ocr_engine import OcrWord
from app.core.ocr_table_reconstruction import reconstruct_table_from_words

# Column start x-positions spaced generously (300px) relative to each
# word's width (50px) -- comfortably clear of the reconstruction
# heuristic's gap threshold (median width * 2.5) in both directions, and
# small compared to the tight in-cell word spacing used elsewhere.
_COLUMNS = [0, 300, 600, 900, 1200, 1500]
_WORD_WIDTH = 50


def _word(text: str, col: int, row: int) -> OcrWord:
    return OcrWord(
        text=text,
        left=_COLUMNS[col],
        top=row * 30,
        width=_WORD_WIDTH,
        height=20,
        line_key=(1, 1, row),
        confidence=90.0,
    )


def _clean_boq_words() -> list[OcrWord]:
    words: list[OcrWord] = []
    rows = [
        ["Item", "Description", "Qty", "Unit", "Rate", "Amount"],
        ["1", "Excavation", "10", "m3", "50.00", "500.00"],
        ["2", "Blockwork", "200", "m2", "75.00", "15000.00"],
        ["3", "Reinforcement", "5", "ton", "3000.00", "15000.00"],
    ]
    for row_index, row in enumerate(rows):
        for col, text in enumerate(row):
            words.append(_word(text, col, row=row_index))
    return words


def test_reconstructs_a_clean_boq_table_into_a_grid() -> None:
    table = reconstruct_table_from_words(_clean_boq_words(), page_number=1)

    assert table is not None
    assert len(table.rows) == 4  # header + 3 data rows
    assert table.rows[0] == ["Item", "Description", "Qty", "Unit", "Rate", "Amount"]
    assert table.rows[1] == ["1", "Excavation", "10", "m3", "50.00", "500.00"]
    assert table.rows[3][5] == "15000.00"


def test_returns_none_for_plain_paragraph_text_with_no_columns() -> None:
    lines = [
        "This quotation is valid for thirty days from the date of issue.",
        "Prices are exclusive of VAT unless otherwise stated above.",
        "Payment terms: fifty percent advance, balance on completion.",
        "Please contact our office for any clarification required.",
    ]
    words: list[OcrWord] = []
    for row_index, line in enumerate(lines):
        left = 0
        for token in line.split():
            words.append(
                OcrWord(
                    text=token,
                    left=left,
                    top=row_index * 30,
                    width=len(token) * 8,
                    height=20,
                    line_key=(1, 1, row_index),
                    confidence=88.0,
                )
            )
            left += len(token) * 8 + 6  # normal word spacing, well under the column-gap threshold

    assert reconstruct_table_from_words(words, page_number=2) is None


def test_returns_none_when_cell_counts_are_too_inconsistent_to_trust() -> None:
    # Deliberately ragged: cell counts per row are [6, 6, 2, 3, 4] -- no
    # single count reaches the majority the heuristic requires, so this
    # must be treated as an uncertain layout rather than a guessed table.
    row_cell_counts = [6, 6, 2, 3, 4]
    words: list[OcrWord] = []
    for row_index, cell_count in enumerate(row_cell_counts):
        for col in range(cell_count):
            words.append(_word(f"cell{col}", col, row=row_index))

    assert reconstruct_table_from_words(words, page_number=3) is None


def test_returns_none_for_no_words() -> None:
    assert reconstruct_table_from_words([], page_number=1) is None
