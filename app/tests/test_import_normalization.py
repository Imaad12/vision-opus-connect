from decimal import Decimal

from app.core.import_normalization import (
    normalize_currency_token,
    normalize_unit,
    normalize_whitespace,
    parse_amount,
    parse_date_maybe,
    reconcile_net_tax_gross,
)


def test_normalize_whitespace_collapses_and_strips() -> None:
    assert normalize_whitespace("  Quoted   Value \n here  ") == "Quoted Value here"
    assert normalize_whitespace("") is None
    assert normalize_whitespace(None) is None


def test_normalize_currency_token_recognizes_aliases() -> None:
    assert normalize_currency_token("AED") == "AED"
    assert normalize_currency_token("Dh") == "AED"
    assert normalize_currency_token("Dhs") == "AED"
    assert normalize_currency_token("Dirham") == "AED"
    assert normalize_currency_token("د.إ") == "AED"
    assert normalize_currency_token("$") == "USD"


def test_normalize_currency_token_returns_none_for_unknown() -> None:
    assert normalize_currency_token("Bitcoin") is None
    assert normalize_currency_token(None) is None


def test_parse_amount_plain_integer() -> None:
    result = parse_amount("1250")
    assert result.value == Decimal("1250")
    assert result.ambiguous is False


def test_parse_amount_thousands_comma_with_decimal_dot_is_unambiguous() -> None:
    result = parse_amount("1,250.00")
    assert result.value == Decimal("1250.00")
    assert result.ambiguous is False


def test_parse_amount_european_dot_thousands_comma_decimal_is_unambiguous() -> None:
    result = parse_amount("1.250,00")
    assert result.value == Decimal("1250.00")
    assert result.ambiguous is False


def test_parse_amount_multiple_thousands_groups_is_unambiguous() -> None:
    # The brief's own worked example: "TOTAL INCLUDING VAT: AED 1,312,500"
    result = parse_amount("1,312,500")
    assert result.value == Decimal("1312500")
    assert result.ambiguous is False


def test_parse_amount_single_comma_three_digits_is_ambiguous() -> None:
    # The brief's explicit example of what must NOT be silently resolved.
    result = parse_amount("1,250")
    assert result.value is None
    assert result.ambiguous is True
    assert result.raw == "1,250"


def test_parse_amount_single_dot_three_digits_is_ambiguous() -> None:
    result = parse_amount("1.250")
    assert result.value is None
    assert result.ambiguous is True


def test_parse_amount_decimal_comma_two_digits_is_unambiguous() -> None:
    result = parse_amount("1250,50")
    assert result.value == Decimal("1250.50")
    assert result.ambiguous is False


def test_parse_amount_with_currency_symbol_extracts_number() -> None:
    result = parse_amount("AED 1,312,500.00")
    assert result.value == Decimal("1312500.00")


def test_parse_amount_empty_or_garbage_returns_none_not_ambiguous() -> None:
    result = parse_amount("N/A")
    assert result.value is None
    assert result.ambiguous is False


# --- Regression: a percentage rate must never be concatenated onto a ---
# --- monetary amount (real archive finding, OCR Phase 1 fix) -----------


def test_parse_amount_percentage_prefix_is_never_folded_into_the_amount() -> None:
    """The real-archive finding this guards against: OCR produced the raw
    string "5% charges SR 900.00" for a VAT line whose actual amount is
    SR 900.00. The naive "strip every non-numeric character and parse
    what's left" approach silently concatenated "5" onto "900.00" into a
    fabricated 5,900.00 -- a confidently-wrong financial value."""
    result = parse_amount("5% charges SR 900.00")
    assert result.value == Decimal("900.00")
    assert result.ambiguous is False


def test_parse_amount_percentage_prefix_variant_with_equals_sign() -> None:
    result = parse_amount("VAT 5% = 900.00")
    assert result.value == Decimal("900.00")
    assert result.ambiguous is False


def test_parse_amount_plain_decimal_still_parses() -> None:
    result = parse_amount("900.00")
    assert result.value == Decimal("900.00")
    assert result.ambiguous is False


def test_parse_amount_currency_prefixed_thousands_still_parses() -> None:
    assert parse_amount("SR 151,955.00").value == Decimal("151955.00")
    assert parse_amount("SAR 168,495.00").value == Decimal("168495.00")


def test_parse_amount_percentage_alone_yields_no_value_not_a_guess() -> None:
    # A rate with no accompanying amount at all -- nothing to extract, and
    # the "5" must never be treated as the amount just because it's the
    # only digit present.
    result = parse_amount("5%")
    assert result.value is None
    assert result.ambiguous is False


def test_parse_amount_two_distinct_amounts_on_one_line_is_ambiguous() -> None:
    # More than one genuine (non-percentage) monetary figure on the same
    # line/cell -- which one is "the" value is genuinely ambiguous and
    # must be flagged for review, never guessed (e.g. by taking the first).
    result = parse_amount("Total 168,495.00 and 500.00 discount")
    assert result.value is None
    assert result.ambiguous is True


def test_parse_amount_negative_amount_still_parses() -> None:
    # Existing behavior (a price adjustment/correction) must survive the
    # tokenization rewrite unchanged.
    assert parse_amount("-150.00").value == Decimal("-150.00")


# --- Regression: minus sign separated from its digits by OCR/typesetting
# --- spacing must not silently lose its sign (adversarial-review finding)


def test_parse_amount_negative_sign_survives_a_space_before_the_digits() -> None:
    """A real OCR/typesetting artifact: a standalone minus sign with a
    gap before its digits ("- 150.00", e.g. a discount/credit line). The
    tokenization rewrite initially lost the sign here (the leading `-?`
    only matched a minus glued directly to a digit), silently turning a
    negative amount positive -- the most dangerous class of transcription
    error, since the wrong value still looks perfectly plausible."""
    assert parse_amount("- 150.00").value == Decimal("-150.00")
    assert parse_amount("SR - 900.00").value == Decimal("-900.00")


def test_parse_amount_hyphenated_identifier_is_not_read_as_negative() -> None:
    """The fix for the above must not overcorrect: a hyphen glued to a
    word (a reference/PO number, not a standalone sign) must never be
    treated as negating the number that follows it."""
    assert parse_amount("Ref-2024").value == Decimal("2024")
    assert parse_amount("PO-2024 total").value == Decimal("2024")


def test_parse_amount_unicode_minus_and_en_dash_are_recognized_as_negative() -> None:
    """Adversarial-review finding: a document/PDF renderer can produce a
    real minus sign (U+2212) or en dash (U+2013) instead of a plain ASCII
    hyphen for a negative amount. Before this fix, neither was recognized
    as a sign at all, so the tokenizer silently dropped it and returned a
    *positive* value -- the same dangerous sign-loss failure mode already
    fixed once for whitespace-separated ASCII minus signs, just triggered
    by a different character instead of different spacing."""
    assert parse_amount("−151,955.00").value == Decimal("-151955.00")  # MINUS SIGN
    assert parse_amount("–151,955.00").value == Decimal("-151955.00")  # EN DASH
    assert parse_amount("SR − 900.00").value == Decimal("-900.00")


def test_parse_amount_quantity_with_unit_suffix_still_parses() -> None:
    # Real archive BOQ-cell shape: "42766.45 LM" -- the unit suffix is not
    # a percentage and must not trigger the ambiguous-multi-token path.
    assert parse_amount("42766.45 LM").value == Decimal("42766.45")


def test_parse_date_maybe_common_formats() -> None:
    from datetime import date

    assert parse_date_maybe("2024-03-15") == date(2024, 3, 15)
    assert parse_date_maybe("15/03/2024") == date(2024, 3, 15)
    assert parse_date_maybe("15 Mar 2024") == date(2024, 3, 15)


def test_parse_date_maybe_unparseable_returns_none() -> None:
    assert parse_date_maybe("sometime next week") is None
    assert parse_date_maybe(None) is None


# --- Regression: real archive trailing OCR punctuation (OCR Phase 4 fix) --
# The real Vinco archive's dates almost universally OCR with the source
# line's own sentence-ending punctuation still attached -- confirmed via
# the real saved OCR output ("Nov 19, 2018.", "November 20, 2018.",
# "November 07, 2018.", "November 29,2018."). The date label itself was
# already found and matched; only the trailing character defeated the
# exact-format parse, silently discarding an otherwise-correct value.


def test_parse_date_maybe_tolerates_trailing_period() -> None:
    from datetime import date

    assert parse_date_maybe("Nov 19, 2018.") == date(2018, 11, 19)
    assert parse_date_maybe("November 20, 2018.") == date(2018, 11, 20)


def test_parse_date_maybe_tolerates_trailing_colon() -> None:
    from datetime import date

    assert parse_date_maybe("Nov 19, 2018:") == date(2018, 11, 19)


def test_parse_date_maybe_tolerates_trailing_semicolon() -> None:
    from datetime import date

    assert parse_date_maybe("Nov 19, 2018;") == date(2018, 11, 19)


def test_parse_date_maybe_without_trailing_punctuation_still_works() -> None:
    from datetime import date

    assert parse_date_maybe("Nov 19, 2018") == date(2018, 11, 19)


def test_parse_date_maybe_via_label_line_with_trailing_period() -> None:
    # The label itself is already stripped by `_pattern_for` before this
    # function ever sees the value -- this proves the exact real shape
    # `extract_quotation_candidate` hands it: "Date: Nov 19, 2018." ->
    # raw_value "Nov 19, 2018." after separator stripping.
    from datetime import date

    assert parse_date_maybe("Nov 19, 2018.") == date(2018, 11, 19)


def test_parse_date_maybe_does_not_strip_a_meaningful_internal_comma() -> None:
    from datetime import date

    # The comma between day and year in "Month DD, YYYY" is never at the
    # end of the string, so it must never be touched by the trailing-
    # punctuation tolerance -- only genuinely harmless trailing characters
    # are stripped.
    assert parse_date_maybe("November 07, 2018.") == date(2018, 11, 7)


def test_parse_date_maybe_trailing_punctuation_does_not_rescue_garbage() -> None:
    # Stripping trailing punctuation must never turn genuinely unparseable
    # text into a fabricated date.
    assert parse_date_maybe("Nov 19, 2018abc.") is None
    assert parse_date_maybe("not a date at all.") is None


# --- Regression: real archive comma-spacing date variants (OCR Phase 4 round 4) --
# Diagnosing why several correctly-bounded real segments remained BLOCKED
# despite good net/tax/gross values found two more real, distinct date-
# format variants -- both around the comma in "Month DD, YYYY", both
# confirmed directly against the real archive's saved OCR output, and
# both different from each other and from the round 2 trailing-
# punctuation fix.


def test_parse_date_maybe_tolerates_space_before_the_comma() -> None:
    # Real archive page 14 (VN/QU/389/18): "Date - November 18 , 2018."
    from datetime import date

    assert parse_date_maybe("November 18 , 2018.") == date(2018, 11, 18)


def test_parse_date_maybe_tolerates_no_space_after_the_comma() -> None:
    # Real archive: confirmed on three separate real documents --
    # pages 19 (VN/QU/390/18), 21 (VN/QU/419/18), and 22 (VN/QU/420/18),
    # all "Date - Month DD,YYYY." with no space after the comma.
    from datetime import date

    assert parse_date_maybe("November 29,2018.") == date(2018, 11, 29)
    assert parse_date_maybe("November 03,2018.") == date(2018, 11, 3)


def test_parse_date_maybe_comma_spacing_combines_with_trailing_punctuation() -> None:
    # Both real artifacts can appear together on the same real line.
    from datetime import date

    assert parse_date_maybe("November 29,2018.") == date(2018, 11, 29)
    assert parse_date_maybe("November 18 , 2018.") == date(2018, 11, 18)


def test_parse_date_maybe_comma_spacing_still_requires_a_real_date() -> None:
    # Normalizing comma whitespace must never rescue genuinely unparseable
    # text -- only whitespace around the comma is ever touched.
    assert parse_date_maybe("see item 3 , 4 for details") is None
    assert parse_date_maybe("November 2018abc,xyz") is None


def test_parse_date_maybe_normal_comma_spacing_is_unaffected() -> None:
    # The already-correct "Month DD, YYYY" shape must keep working
    # unchanged -- the new normalization is a no-op on it.
    from datetime import date

    assert parse_date_maybe("November 27, 2018") == date(2018, 11, 27)


def test_normalize_unit_aliases() -> None:
    assert normalize_unit("SQM") == "m2"
    assert normalize_unit("Sq.M") == "m2"
    assert normalize_unit("nos") == "nos"
    assert normalize_unit("Unrecognized-Unit") == "Unrecognized-Unit"


def test_reconcile_net_tax_gross_derives_missing_net() -> None:
    result = reconcile_net_tax_gross(None, Decimal("62500"), Decimal("1312500"))
    assert result.net == Decimal("1250000")
    assert result.derived_field == "net"


def test_reconcile_net_tax_gross_derives_missing_gross() -> None:
    result = reconcile_net_tax_gross(Decimal("1250000"), Decimal("62500"), None)
    assert result.gross == Decimal("1312500")
    assert result.derived_field == "gross"


def test_reconcile_net_tax_gross_derives_missing_tax() -> None:
    result = reconcile_net_tax_gross(Decimal("1250000"), None, Decimal("1312500"))
    assert result.tax == Decimal("62500")
    assert result.derived_field == "tax"


def test_reconcile_net_tax_gross_never_guesses_from_only_one_value() -> None:
    # Only the gross figure is known — deriving net/tax would require
    # assuming a VAT rate, which this application never fabricates.
    result = reconcile_net_tax_gross(None, None, Decimal("1312500"))
    assert result.net is None
    assert result.tax is None
    assert result.derived_field is None


def test_reconcile_net_tax_gross_leaves_all_three_untouched_when_all_present() -> None:
    result = reconcile_net_tax_gross(Decimal("100"), Decimal("5"), Decimal("106"))
    assert (result.net, result.tax, result.gross) == (Decimal("100"), Decimal("5"), Decimal("106"))
    assert result.derived_field is None
