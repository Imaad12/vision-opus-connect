from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.po_extraction import extract_purchase_order_candidate

PO_TEXT = """\
PO Date: 15/03/2025
Quotation Reference: VN/QU/500/25
Net Amount: 55,000.00
VAT Amount: 2,750.00
Total Including VAT: 57,750.00
"""


def test_extracts_the_reference_date_and_amounts() -> None:
    result = extract_purchase_order_candidate(PO_TEXT, [])

    assert result.po_reference_number == "VN/QU/500/25"
    assert result.po_date == date(2025, 3, 15)
    assert result.net_value == Decimal("55000.00")
    assert result.tax_value == Decimal("2750.00")
    assert result.gross_value == Decimal("57750.00")


def test_missing_gross_is_derived_from_net_and_tax() -> None:
    text = "Quotation Reference: VN/QU/501/25\nNet Amount: 10,000.00\nVAT Amount: 500.00\n"
    result = extract_purchase_order_candidate(text, [])

    assert result.gross_value == Decimal("10500.00")


def test_no_recognizable_fields_returns_all_none() -> None:
    result = extract_purchase_order_candidate("This is an unrelated cover letter.\n", [])

    assert result.po_reference_number is None
    assert result.po_date is None
    assert result.net_value is None
    assert result.tax_value is None
    assert result.gross_value is None


def test_bare_reference_label_is_recognized() -> None:
    """Per current business practice a PO's own reference number is the
    quotation's reference as printed on the PO — a bare 'Reference:' label
    (no 'quotation' qualifier) must still be recognized, mirroring the
    same bare-label tolerance already accepted for quotation extraction."""
    text = "Reference: VN/QU/502/25\nDate: 01/04/2025\n"
    result = extract_purchase_order_candidate(text, [])

    assert result.po_reference_number == "VN/QU/502/25"
    assert result.po_date == date(2025, 4, 1)
