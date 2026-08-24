from datetime import date
from decimal import Decimal

from app.core.enums import ConfidenceLevel, ImportDocumentKind
from app.core.import_extraction import (
    extract_boq_rows,
    extract_candidates,
    extract_quotation_candidate,
    find_distinct_quotation_dates,
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
    # VAT is genuinely not determinable from this text (no label matched,
    # nothing to reconcile) -- the business rule applies: tax_value is
    # normalized to SAR 0.00, flagged LOW confidence (never HIGH, since it
    # was never actually read off the document), never guessed via a rate.
    assert result.tax_value == Decimal("0.00")
    assert result.field_confidence == {"tax_value": ConfidenceLevel.LOW.value}
    assert result.raw_values["tax_value_basis"] == "undetermined_zero_applied"


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


# --- Regression: real archive "Kind Attn." client label (OCR Phase 4 fix) --
# Every real Vinco archive document that labels its client contact prints
# "Kind Attn." (with the period), never bare "Attn" at the start of a
# line -- confirmed against the real archive's saved OCR output, where
# `client_name` was never once populated from any real document despite
# "attn" already being a recognized label alias.


def test_kind_attn_label_is_recognized_for_client_name() -> None:
    result = extract_quotation_candidate("Kind Attn. : Mr. Syed Nazir Ali\n", [])
    assert result.client_name == "Mr. Syed Nazir Ali"


def test_kind_attn_label_with_hyphen_separator_is_recognized() -> None:
    result = extract_quotation_candidate("Kind Attn. - Mr. Nelson\n", [])
    assert result.client_name == "Mr. Nelson"


def test_kind_attn_label_with_doubled_em_dash_and_colon_separator_is_recognized() -> None:
    # Real archive shape: an em dash *and* a colon together, with a space
    # between them ("Kind Attn. — : Mr. Nelson,").
    result = extract_quotation_candidate("Kind Attn. — : Mr. Nelson,\n", [])
    assert result.client_name == "Mr. Nelson,"


def test_kind_attn_label_without_a_period_is_still_recognized() -> None:
    result = extract_quotation_candidate("Kind Attn: Mr. Ismail Shareef\n", [])
    assert result.client_name == "Mr. Ismail Shareef"


def test_kind_attn_takes_priority_over_bare_attn_label() -> None:
    # "kind attn" is the more specific label and must be tried first (see
    # `_FIELD_ORDER`) so it does not fall through to bare "attn" matching
    # only "Attn." with "Kind" left dangling as part of the separator gap.
    result = extract_quotation_candidate("Kind Attn. : Mr. Scott Smith\n", [])
    assert result.client_name == "Mr. Scott Smith"
    assert "Kind" not in (result.client_name or "")


# --- Regression: real archive table-totals row shape (OCR Phase 4 fix) --
# The real Vinco archive's BOQ totals rows OCR as e.g. "Total (SAR) |
# 51,644.77" and "Sub Total (SAR) | 49,185.50" -- a table-cell pipe
# separator instead of a colon, with the currency printed as part of the
# label's own header cell rather than the value. Neither shape matched
# `_pattern_for`'s original `[:\-»]` separator class (confirmed against
# the real archive's saved OCR output), so these totals were never
# extracted at all.


def test_pipe_separator_from_ocrd_table_cell_is_recognized() -> None:
    result = extract_quotation_candidate("Total (SAR) | 51,644.77\n", [])
    assert result.gross_value == Decimal("51644.77")


def test_pipe_separator_with_sub_total_label_is_recognized() -> None:
    result = extract_quotation_candidate("Sub Total (SAR) | 49,185.50\n", [])
    assert result.net_value == Decimal("49185.50")


def test_parenthetical_currency_annotation_without_pipe_still_requires_a_real_separator() -> None:
    # The parenthetical addition only bridges label -> separator; it must
    # not make the separator itself optional.
    result = extract_quotation_candidate("Total (SAR) 51,644.77\n", [])
    assert result.gross_value is None


def test_leading_ocr_noise_before_the_label_is_a_known_unresolved_case() -> None:
    # Real archive shape ("ea ee Sub Total (SAR) | 49,185.50 |", "eae Total
    # (SAR) |__22,050.00") -- Tesseract garbles a blank/empty leading table
    # cell into noise characters before the label itself. This is
    # deliberately NOT handled by loosening the line-start anchor (that
    # would risk matching label text embedded mid-sentence -- the same
    # over-broad-matching risk the bare-whitespace-separator restriction
    # above already guards against); it falls through to the VAT/financial
    # safety net (missing net_value blocks confirmation) rather than being
    # guessed. Documents this as a known, accepted limitation, not a bug.
    result = extract_quotation_candidate("eae Total (SAR) |__22,050.00\n", [])
    assert result.gross_value is None


# --- VAT business rule: "genuinely not determinable" -> SAR 0.00 -------
# (OCR Phase 4). Real archive wording confirmed via the saved OCR output:
# "VAT 5% not included in our offer", "5% VAT will be charged extra" --
# both state VAT is excluded but print no absolute SAR figure, so no VAT
# amount is determinable without assuming the printed rate (never done).
# No genuine "VAT inclusive" wording was found anywhere in the real
# archive, but the distinction must still hold for any future document
# that does use it -- see `_apply_vat_determination_when_undetermined`.


def test_vat_amount_explicitly_printed_is_extracted_normally_untouched_by_the_new_rule() -> None:
    result = extract_quotation_candidate("VAT Amount: 62,500.00\n", [])
    assert result.tax_value == Decimal("62500.00")
    assert result.field_confidence["tax_value"] == ConfidenceLevel.HIGH.value
    assert "tax_value_basis" not in result.raw_values


def test_vat_excluded_no_amount_wording_normalizes_to_zero_with_a_note() -> None:
    text = "Net Amount: 100,000.00\n3. VAT 5% not included in our offer\n"
    result = extract_quotation_candidate(text, [])
    assert result.net_value == Decimal("100000.00")
    assert result.tax_value == Decimal("0.00")
    assert result.field_confidence["tax_value"] == ConfidenceLevel.LOW.value
    assert result.raw_values["tax_value_basis"] == "undetermined_zero_applied"
    assert "not includ" in result.raw_values["tax_value_note"].lower()


def test_vat_will_be_charged_extra_wording_normalizes_to_zero() -> None:
    text = "Net Amount: 42,766.45\n5% VAT will be charged extra\n"
    result = extract_quotation_candidate(text, [])
    assert result.tax_value == Decimal("0.00")
    assert result.raw_values["tax_value_basis"] == "undetermined_zero_applied"


def test_vat_never_inferred_as_a_percentage_of_net_even_when_a_rate_is_printed() -> None:
    # The business rule is an explicit fixed SAR 0.00, never a computed
    # rate*net figure -- confirms no 5%/15% multiplication ever happens.
    text = "Net Amount: 100,000.00\nVAT 5% not included in our offer\n"
    result = extract_quotation_candidate(text, [])
    assert result.tax_value == Decimal("0.00")
    assert result.tax_value != Decimal("100000.00") * Decimal("0.05")
    assert result.tax_value != Decimal("100000.00") * Decimal("0.15")


def test_vat_inclusive_wording_is_tagged_but_does_not_fabricate_a_split() -> None:
    # A distinct internal state from "undetermined": the printed total is
    # understood to already include VAT, so no separate figure is expected
    # and none is invented -- `tax_value` stays None rather than being
    # forced to the "not determinable" 0.00 default.
    text = "Total Amount: 179,340.00\nAll prices are inclusive of VAT.\n"
    result = extract_quotation_candidate(text, [])
    assert result.gross_value == Decimal("179340.00")
    assert result.tax_value is None
    assert result.raw_values["tax_value_basis"] == "vat_inclusive"
    assert "tax_value_note" not in result.raw_values


def test_vat_inclusive_and_undetermined_are_distinguishable_internal_states() -> None:
    inclusive = extract_quotation_candidate("Total Amount: 100.00\nPrices include VAT.\n", [])
    undetermined = extract_quotation_candidate("Net Amount: 100.00\n", [])
    assert inclusive.raw_values["tax_value_basis"] != undetermined.raw_values["tax_value_basis"]
    assert inclusive.tax_value is None
    assert undetermined.tax_value == Decimal("0.00")


def test_vat_derived_algebraically_from_net_and_gross_is_not_overridden_by_the_new_rule() -> None:
    # Pre-existing `reconcile_net_tax_gross` behavior (unmodified) must
    # still take priority: a real, derivable tax figure is never replaced
    # by the "undetermined" 0.00 default.
    text = "Net Amount: 1,250,000.00\nTotal Including VAT: 1,312,500.00\n"
    result = extract_quotation_candidate(text, [])
    assert result.tax_value == Decimal("62500.00")
    assert result.field_confidence["tax_value"] == ConfidenceLevel.NEEDS_REVIEW.value
    assert "tax_value_basis" not in result.raw_values


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


# --- Regression: distinct-date detection closes a real splicing gap ------
# Adversarial-review finding: reference-counting alone missed the case
# where one document's reference survives OCR but a *different* document's
# date and net value survive elsewhere in the same file -- producing a
# single spliced candidate (real reference + wrong document's date/total)
# that reference-counting alone (only one reference ever found) would
# never flag, and every individually-matched field reports HIGH
# confidence. Counting distinct dates is a second, independent signal.


def test_find_distinct_quotation_dates_single_document() -> None:
    dates = find_distinct_quotation_dates("Reference: VN/QU/412/18\nDate: 27/11/2018\n", [])
    assert dates == [date(2018, 11, 27)]


def test_find_distinct_quotation_dates_detects_multiple_documents() -> None:
    text = (
        "Quotation Reference: 444 REV / 18\nDate: 23.12.2018\n"
        "--- Page 8 ---\n"
        "Date: 27/11/2018\nNet Amount: 151,955.00\n"
    )
    dates = find_distinct_quotation_dates(text, [])
    assert dates == [date(2018, 12, 23), date(2018, 11, 27)]


def test_find_distinct_quotation_dates_ignores_unparseable_text() -> None:
    # A date-labeled line whose value doesn't actually parse as a date is
    # not reliable evidence of a second document -- excluded, not counted.
    text = "Date: 27/11/2018\nDate: not a real date\n"
    assert find_distinct_quotation_dates(text, []) == [date(2018, 11, 27)]


def test_find_distinct_quotation_dates_same_date_different_formatting_is_one_date() -> None:
    # Formatting differences alone (e.g. the same date OCR'd slightly
    # differently across two lines) must not look like two documents.
    text = "Date: 27/11/2018\nQuote Date: 2018-11-27\n"
    assert find_distinct_quotation_dates(text, []) == [date(2018, 11, 27)]


def test_extract_candidates_reports_distinct_dates() -> None:
    raw = RawExtraction(text=SAMPLE_QUOTATION_TEXT, tables=[])
    result = extract_candidates(raw)
    assert result.distinct_dates == [date(2024, 3, 15)]


def test_reference_survives_but_a_different_documents_date_and_total_do_not_merge_undetected() -> None:
    """Direct reproduction of the adversarial-review finding: document A's
    reference and date are clean; document B's reference line was lost to
    OCR entirely, but its (different) date and net value survived. Before
    this fix, `distinct_references` alone found only one reference (A's)
    and the whole file was treated as a single document -- silently
    splicing A's reference/date onto B's unrelated total. `distinct_dates`
    must now independently catch this."""
    text = (
        "Quotation Reference: 444 REV / 18\nDate: 23.12.2018\n"
        "--- Page 8 ---\n"
        "Date: 27/11/2018\nNet Amount: 151,955.00\n"
    )
    result = extract_candidates(RawExtraction(text=text, tables=[]))
    assert len(result.distinct_references) <= 1  # the gap: reference alone doesn't catch it
    assert len(result.distinct_dates) > 1  # the fix: dates do
