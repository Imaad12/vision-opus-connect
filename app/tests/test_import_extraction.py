from decimal import Decimal

from app.core.enums import ConfidenceLevel, ImportDocumentKind
from app.core.import_extraction import extract_boq_rows, extract_candidates, extract_quotation_candidate
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
