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


def test_parse_date_maybe_common_formats() -> None:
    from datetime import date

    assert parse_date_maybe("2024-03-15") == date(2024, 3, 15)
    assert parse_date_maybe("15/03/2024") == date(2024, 3, 15)
    assert parse_date_maybe("15 Mar 2024") == date(2024, 3, 15)


def test_parse_date_maybe_unparseable_returns_none() -> None:
    assert parse_date_maybe("sometime next week") is None
    assert parse_date_maybe(None) is None


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
