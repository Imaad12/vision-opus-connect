from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.po_extraction import extract_client_award_evidence_candidate

PO_TEXT = """\
PO Date: 15/03/2025
Quotation Reference: VN/QU/500/25
Net Amount: 55,000.00
VAT Amount: 2,750.00
Total Including VAT: 57,750.00
"""


def test_extracts_the_reference_date_and_amounts() -> None:
    result = extract_client_award_evidence_candidate(PO_TEXT, [])

    assert result.po_reference_number == "VN/QU/500/25"
    assert result.po_date == date(2025, 3, 15)
    assert result.net_value == Decimal("55000.00")
    assert result.tax_value == Decimal("2750.00")
    assert result.gross_value == Decimal("57750.00")


def test_missing_gross_is_derived_from_net_and_tax() -> None:
    text = "Quotation Reference: VN/QU/501/25\nNet Amount: 10,000.00\nVAT Amount: 500.00\n"
    result = extract_client_award_evidence_candidate(text, [])

    assert result.gross_value == Decimal("10500.00")


def test_no_recognizable_fields_returns_all_none() -> None:
    result = extract_client_award_evidence_candidate("This is an unrelated cover letter.\n", [])

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
    result = extract_client_award_evidence_candidate(text, [])

    assert result.po_reference_number == "VN/QU/502/25"
    assert result.po_date == date(2025, 4, 1)


# --- Real-document regressions (Eastern Agriculture Company PO EAC/26/NAU/1923,
# first genuine client-issued PO validated against this extractor) ------------
#
# All text below is the actual Tesseract OCR output for this real document,
# not a paraphrase -- see PO_ARCHITECTURE.md for the validation round this
# came from.


def test_quotation_ref_abbreviation_is_recognized() -> None:
    """Real wording: this client's PO template prints 'Quotation Ref.'
    (abbreviated), never the unabbreviated 'Quotation Reference' the base
    label list already covered."""
    text = "Quotation Ref. : PQ-SRF-2025-176\n"
    result = extract_client_award_evidence_candidate(text, [])

    assert result.po_reference_number == "PQ-SRF-2025-176"


def test_two_column_header_bleed_reference_is_still_recovered() -> None:
    """Real OCR line: 'PO. Box-105 Quotation Ref. : PQ-SRF-2025-176' --
    a two-column PO header table (supplier address | order reference)
    flattened into one OCR line, with the left column's leftover text
    still attached before the right column's own label. The normal
    line-start-anchored scan cannot match this (by design -- see
    `_pattern_for`'s own docstring on why bare proximity is never
    trusted); the `search()`-based fallback, scoped only to labels
    containing the word 'quotation', recovers it."""
    text = "PO. Box-105 Quotation Ref. : PQ-SRF-2025-176\n"
    result = extract_client_award_evidence_candidate(text, [])

    assert result.po_reference_number == "PQ-SRF-2025-176"


def test_two_column_bleed_fallback_does_not_fire_for_a_bare_reference_label() -> None:
    """The unanchored fallback is deliberately scoped to labels containing
    the specific word 'quotation' only -- a bare 'Reference:' preceded by
    unrelated leftover text must NOT be recovered this way, since a bare
    'reference' is common enough prose that an unanchored match on it
    would risk false positives elsewhere in a document."""
    text = "See attached drawing package. Reference: DWG-100\n"
    result = extract_client_award_evidence_candidate(text, [])

    assert result.po_reference_number is None


def test_real_po_date_format_day_abbreviated_month_two_digit_year() -> None:
    """Real wording: 'PO Date : 15-May-26' -- this client's own PO
    template uses day-hyphen-Mon-hyphen-2-digit-year, a format no
    quotation in the real archive has ever used (which always prints a
    4-digit year)."""
    text = "PO Date : 15-May-26\n"
    result = extract_client_award_evidence_candidate(text, [])

    assert result.po_date == date(2026, 5, 15)


def test_real_vat_and_grand_total_with_no_separator_derive_net_for_free() -> None:
    """Real OCR lines from the same document's totals block:
    'Vat 15% 73500.00' and 'Grand Total (SAR)} 563,500.00' (the '}' is a
    real OCR misread of the closing parenthesis/table border). Neither
    has a label:value separator. Net value is never given its own label
    on this document at all ('Total 490,000.00' is bare and ambiguous
    with gross_value's own 'total' label) -- it is recovered for free by
    the existing net/tax/gross reconciliation once tax and gross are
    both found here, exactly as already happens on the quotation side."""
    text = "Vat 15% 73500.00\nGrand Total (SAR)} 563,500.00\n"
    result = extract_client_award_evidence_candidate(text, [])

    assert result.tax_value == Decimal("73500.00")
    assert result.gross_value == Decimal("563500.00")
    assert result.net_value == Decimal("490000.00")


def test_your_vendor_ref_label_recovers_across_a_column_bleed() -> None:
    """Real OCR line from a second, independent real client PO template
    (WAHAH Electric Supply Co.): 'Fax 966138674567 Your/Vendor Ref. |
    QQUTNO# 26-53' -- the fax number (left column) bled onto the same
    line as the 'Your/Vendor Ref.' column, exactly the same shape as the
    Eastern Agriculture Company PO's 'Quotation Ref.' case above, using a
    completely different label wording."""
    text = "Fax 966138674567 Your/Vendor Ref. | QQUTNO# 26-53\n"
    result = extract_client_award_evidence_candidate(text, [])

    assert result.po_reference_number == "QQUTNO# 26-53"


def test_your_vendor_ref_label_alone_on_a_line_is_not_a_false_positive() -> None:
    """Known, accepted limitation, real evidence: a third real client PO
    template (Saudi Power Transformers Co.) also uses 'Your/Vendor Ref.'
    but its OCR reading order separates the label from its value by many
    unrelated lines (a genuine table-reconstruction problem, not a
    same-line bleed) -- this must not fabricate a value from nothing."""
    text = "+966138674567 Your/Vendor Ref.\n"
    result = extract_client_award_evidence_candidate(text, [])

    assert result.po_reference_number is None


def test_real_client_po_full_header_and_totals_block() -> None:
    """The real, combined OCR text (header + totals) for this document,
    end to end through the extractor -- the actual validation specimen,
    not a synthetic reconstruction."""
    text = (
        "Saad Fahad Al-Hajri Est PO Number : EAC/26/NA/1923\n"
        "PO Date : 15-May-26\n"
        "PO. Box-105 Quotation Ref. : PQ-SRF-2025-176\n"
        "Dammam-31921, Saudi Arabia Quotation Date : 14-May-26\n"
        "Buyer Name : Mohammed Naushad Ali\n"
        "Total 490,000.00\n"
        "Vat 15% 73500.00\n"
        "Grand Total (SAR)} 563,500.00\n"
    )
    result = extract_client_award_evidence_candidate(text, [])

    assert result.po_reference_number == "PQ-SRF-2025-176"
    assert result.po_date == date(2026, 5, 15)
    assert result.tax_value == Decimal("73500.00")
    assert result.gross_value == Decimal("563500.00")
    assert result.net_value == Decimal("490000.00")
