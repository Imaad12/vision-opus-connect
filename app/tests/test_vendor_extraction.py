"""Tests for `app.core.vendor_extraction` -- deterministic vendor identity
field extraction, document-kind agnostic (see the module's own docstring).
These are synthetic fixtures, not real-document validation -- no real
supplier/vendor document archive has been ingested yet; see
PO_ARCHITECTURE.md's Supplier/Vendor intelligence section for the same
discipline already applied to quotation/PO extraction."""

from __future__ import annotations

from app.core.vendor_extraction import extract_vendor_candidate


def test_extracts_vendor_name_from_a_labeled_line() -> None:
    result = extract_vendor_candidate("Supplier Name: Gulf Steel Trading LLC\n", [])

    assert result.vendor_name == "Gulf Steel Trading LLC"


def test_extracts_vendor_tax_number_from_a_labeled_line() -> None:
    result = extract_vendor_candidate("VAT Registration Number: 100234567800003\n", [])

    assert result.vendor_tax_number == "100234567800003"


def test_extracts_both_name_and_tax_number_together() -> None:
    text = "Supplier: Al Rashid Building Materials\nTRN: 987654321000123\n"
    result = extract_vendor_candidate(text, [])

    assert result.vendor_name == "Al Rashid Building Materials"
    assert result.vendor_tax_number == "987654321000123"


def test_more_specific_label_wins_over_bare_supplier_label() -> None:
    # "Supplier Name:" is a longer, more specific label than bare
    # "Supplier:" -- the field order (longest label first) must prefer it
    # when both happen to appear, same discipline as quotation's own bare
    # "reference" label being lowest priority.
    text = "Supplier Name: Correct Vendor Co\nSupplier: Correct Vendor Co\n"
    result = extract_vendor_candidate(text, [])

    assert result.vendor_name == "Correct Vendor Co"


def test_no_recognizable_vendor_fields_returns_none_not_a_guess() -> None:
    result = extract_vendor_candidate("This is an unrelated cover letter with no vendor mentioned.\n", [])

    assert result.vendor_name is None
    assert result.vendor_tax_number is None


def test_bare_reference_style_label_still_requires_a_real_separator() -> None:
    # Mirrors `import_extraction`'s own "Reference Section 3.2 discusses"
    # regression: bare whitespace after the label word must never be
    # treated as a separator (that would match ordinary prose).
    result = extract_vendor_candidate("Vendor management is important for this project.\n", [])

    assert result.vendor_name is None


def test_field_confidence_is_recorded_high_for_a_direct_match() -> None:
    result = extract_vendor_candidate("Vendor Name: Test Supplier Co\n", [])

    assert result.field_confidence["vendor_name"] == "HIGH"


def test_raw_values_preserve_exactly_what_was_extracted() -> None:
    result = extract_vendor_candidate("Supplier Name: ABC Trading\n", [])

    assert result.raw_values["vendor_name"] == "ABC Trading"
