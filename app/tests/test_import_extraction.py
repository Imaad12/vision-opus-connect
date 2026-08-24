from decimal import Decimal

from app.core.enums import ConfidenceLevel, ImportDocumentKind
from app.core.import_extraction import (
    extract_boq_rows,
    extract_candidates,
    extract_quotation_candidate,
    find_distinct_quotation_references,
)
from app.importers.base import ExtractedTable, RawExtraction

SAMPLE_QUOTATION_TEXT = """\
QUOTATION

Quotation Number: Q-2024-0091
Quotation Date: 15/03/2024
Client: ABC Holdings
Project: Villa ABC Renovation
Project Number: VC-2024-018
Currency: AED
Net Amount: AED 1,250,000.00
VAT Amount: AED 62,500.00
Total Including VAT: AED 1,312,500.00
Valid Until: 30/04/2024
Payment Terms: 30 days from invoice
"""

BOQ_TABLE_ROWS = [
    ["Item", "Description", "Trade", "Unit", "Qty", "Rate", "Amount"],
    ["1", "Excavation works", "Civil", "m3", "100", "50.00", "5000.00"],
    ["2", "Concrete blockwork", "Civil", "m2", "200", "75.00", "15300.00"],  # 200*75=15000, mismatch
    ["3", "", "", "", "", "", ""],
]


def test_extract_quotation_candidate_finds_all_labeled_fields() -> None:
    result = extract_quotation_candidate(SAMPLE_QUOTATION_TEXT, [])

    assert result.quotation_number == "Q-2024-0091"
    assert result.client_name == "ABC Holdings"
    assert result.project_name == "Villa ABC Renovation"
    assert result.project_number == "VC-2024-018"
    assert result.currency == "AED"
    assert result.net_value == Decimal("1250000.00")
    assert result.tax_value == Decimal("62500.00")
    assert result.gross_value == Decimal("1312500.00")
    assert result.payment_terms == "30 days from invoice"


def test_extract_quotation_candidate_records_raw_values_and_confidence() -> None:
    result = extract_quotation_candidate(SAMPLE_QUOTATION_TEXT, [])

    assert "AED 1,250,000.00" in result.raw_values["net_value"]
    assert result.field_confidence["net_value"] == ConfidenceLevel.HIGH.value
    assert result.field_confidence["quotation_number"] == ConfidenceLevel.HIGH.value


def test_extract_quotation_candidate_missing_fields_stay_none() -> None:
    result = extract_quotation_candidate("Nothing useful here.", [])
    assert result.quotation_number is None
    assert result.net_value is None
    assert result.field_confidence == {}


def test_extract_quotation_candidate_reads_two_column_table_rows() -> None:
    table = ExtractedTable(
        name="Header",
        rows=[["Quotation Number", "Q-555"], ["Client", "XYZ Contracting"]],
    )
    result = extract_quotation_candidate(None, [table])
    assert result.quotation_number == "Q-555"
    assert result.client_name == "XYZ Contracting"


def test_extract_quotation_candidate_derives_missing_net_when_tax_and_gross_present() -> None:
    text = "VAT Amount: 62,500.00\nTotal Including VAT: 1,312,500.00\n"
    result = extract_quotation_candidate(text, [])
    assert result.net_value == Decimal("1250000.00")
    assert result.field_confidence["net_value"] == ConfidenceLevel.NEEDS_REVIEW.value


def test_extract_boq_rows_maps_columns_and_flags_mismatch() -> None:
    table = ExtractedTable(name="BOQ", rows=BOQ_TABLE_ROWS)
    rows = extract_boq_rows([table])

    assert len(rows) == 2
    first, second = rows

    assert first.description == "Excavation works"
    assert first.category_label == "Civil"
    assert first.quantity == Decimal("100")
    assert first.unit_rate == Decimal("50.00")
    assert first.extracted_amount == Decimal("5000.00")
    assert first.calculated_amount == Decimal("5000.00")
    assert first.amount_flagged is False

    assert second.extracted_amount == Decimal("15300.00")
    assert second.calculated_amount == Decimal("15000.00")
    assert second.amount_flagged is True


def test_extract_boq_rows_skips_tables_without_a_recognizable_header() -> None:
    table = ExtractedTable(name="Notes", rows=[["Just", "some", "text"], ["not", "a", "boq"]])
    assert extract_boq_rows([table]) == []


def test_extract_candidates_classifies_quotation_kind() -> None:
    raw = RawExtraction(text=SAMPLE_QUOTATION_TEXT, tables=[])
    result = extract_candidates(raw)
    assert result.document_kind == ImportDocumentKind.QUOTATION


def test_extract_candidates_classifies_boq_kind_when_only_rows_found() -> None:
    raw = RawExtraction(text=None, tables=[ExtractedTable(name="BOQ", rows=BOQ_TABLE_ROWS)])
    result = extract_candidates(raw)
    assert result.document_kind == ImportDocumentKind.BOQ
    assert len(result.boq_rows) == 2


def test_extract_candidates_classifies_unknown_when_nothing_found() -> None:
    raw = RawExtraction(text="Just a random letter, nothing structured.", tables=[])
    result = extract_candidates(raw)
    assert result.document_kind == ImportDocumentKind.UNKNOWN
    assert result.boq_rows == []


# --- Regression: real archive field labels (OCR Phase 1 fix) -----------
# The real Vinco archive prints bare "Reference:" (every VN/QU/* document)
# or "Quotation Reference:" (the 444/444 REV documents) for the
# quotation's own reference number -- neither was in the original label
# vocabulary, so even a flawless OCR read never populated
# `quotation_number` against real documents.


def test_quotation_reference_label_is_recognized() -> None:
    result = extract_quotation_candidate("Quotation Reference: 444 REV / 18\n", [])
    assert result.quotation_number == "444 REV / 18"


def test_quotation_reference_label_is_recognized_without_rev_suffix() -> None:
    result = extract_quotation_candidate("Quotation Reference: 444 / 18\n", [])
    assert result.quotation_number == "444 / 18"


def test_bare_reference_label_is_recognized() -> None:
    result = extract_quotation_candidate("Reference: VN/QU/412/18\n", [])
    assert result.quotation_number == "VN/QU/412/18"


def test_bare_reference_label_yields_to_a_more_specific_label_found_first() -> None:
    # Real archive shape: "Quotation Reference:" near the top of the
    # document, and an unrelated "Reference: <correspondence note>" row
    # later in an info table. The more specific label must win.
    text = "Quotation Reference: 444 REV / 18\nReference : Your mail inquiry dated 26th November 2018\n"
    result = extract_quotation_candidate(text, [])
    assert result.quotation_number == "444 REV / 18"


def test_bare_reference_label_with_no_more_specific_label_is_a_known_limitation() -> None:
    # Documented, accepted trade-off (see the comment in import_extraction.py
    # next to `_FIELD_LABELS["quotation_number"]`): with no "quotation
    # reference"/"quote no" line anywhere on the document, a bare
    # "Reference:" row is taken at face value even when it means something
    # else entirely -- the same shape as "attn" already being accepted for
    # `client_name`. This test documents the behavior, not a bug to fix.
    result = extract_quotation_candidate("Reference: Your mail inquiry dated 26th November 2018\n", [])
    assert result.quotation_number == "Your mail inquiry dated 26th November 2018"


def test_reference_label_with_ocr_guillemet_colon_substitution_is_recognized() -> None:
    # Real, observed Tesseract artifact on this exact archive: a printed
    # colon OCR'd as "»" rather than ":".
    result = extract_quotation_candidate("Reference » VN/QU/417/18\n", [])
    assert result.quotation_number == "VN/QU/417/18"


def test_reference_label_still_requires_a_real_separator_not_bare_whitespace() -> None:
    # Deliberately NOT supported -- see the comment on `_pattern_for`. Bare
    # whitespace as a stand-in colon would match ordinary prose just as
    # readily as a real label:value line.
    result = extract_quotation_candidate("Reference Section 3.2 discusses further details\n", [])
    assert result.quotation_number is None


# --- Regression: multi-quotation-per-file detection (OCR Phase 1 fix) --


def test_find_distinct_quotation_references_single_document() -> None:
    refs = find_distinct_quotation_references("Reference: VN/QU/412/18\nDate: Nov 27, 2018\n", [])
    assert refs == ["VN/QU/412/18"]


def test_find_distinct_quotation_references_detects_multiple_documents() -> None:
    # The real archive scenario: page 1's quotation A followed later in
    # the same file by page 8's quotation B.
    text = (
        "Quotation Reference: 444 REV / 18\nDate: 23.12.2018\n"
        "--- Page 8 ---\n"
        "Reference: VN/QU/412/18\nDate: Nov 27, 2018\n"
    )
    refs = find_distinct_quotation_references(text, [])
    assert refs == ["444 REV / 18", "VN/QU/412/18"]


def test_find_distinct_quotation_references_empty_when_none_found() -> None:
    assert find_distinct_quotation_references("Nothing structured here.\n", []) == []


def test_extract_candidates_reports_distinct_references() -> None:
    raw = RawExtraction(text=SAMPLE_QUOTATION_TEXT, tables=[])
    result = extract_candidates(raw)
    assert result.distinct_references == ["Q-2024-0091"]


def test_extract_candidates_reports_multiple_distinct_references() -> None:
    text = "Reference: VN/QU/412/18\n" "Reference: VN/QU/417/18\n"
    raw = RawExtraction(text=text, tables=[])
    result = extract_candidates(raw)
    assert result.distinct_references == ["VN/QU/412/18", "VN/QU/417/18"]
