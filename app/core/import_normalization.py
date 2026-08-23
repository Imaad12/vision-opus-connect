"""Deterministic normalization for values extracted from source documents.

Pure functions only — no I/O, no database, no AI/network calls (Phase 4
explicitly excludes both; see IMPORT_ARCHITECTURE.md). These turn messy
extracted text ("د.إ", "1,250", "TOTAL INCLUDING VAT: AED 1,312,500") into
values a human can review, without ever guessing past genuine ambiguity —
see `parse_amount` below for the rule the brief calls out explicitly:
"1,250" must not silently become `1250` when the format is ambiguous.

This module never talks to `app.core.financial_engine` for anything other
than the two pure net/tax/gross helpers it already defines
(`calculate_net_of_tax`, `calculate_gross_amount`) — the arithmetic itself
must never be duplicated here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.core.financial_engine import calculate_gross_amount, calculate_net_of_tax

# --- Whitespace -------------------------------------------------------------


def normalize_whitespace(text: str | None) -> str | None:
    """Collapse runs of whitespace (including newlines/tabs from a PDF/Excel
    cell) into single spaces, and strip leading/trailing space."""
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


# --- Currency -----------------------------------------------------------------

_CURRENCY_ALIASES: dict[str, str] = {
    "AED": "AED",
    "DHS": "AED",
    "DH": "AED",
    "DHM": "AED",
    "DIRHAM": "AED",
    "DIRHAMS": "AED",
    "د.إ": "AED",
    "USD": "USD",
    "US$": "USD",
    "$": "USD",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "EUR": "EUR",
    "€": "EUR",
    "EURO": "EUR",
    "EUROS": "EUR",
    "GBP": "GBP",
    "£": "GBP",
    "POUND": "GBP",
    "POUNDS": "GBP",
    "SAR": "SAR",
    "SR": "SAR",
    "RIYAL": "SAR",
    "RIYALS": "SAR",
    "ريال": "SAR",
}


def normalize_currency_token(text: str | None) -> str | None:
    """Map a currency symbol/word/abbreviation to its ISO-4217 code, e.g.
    "Dh", "د.إ", and "Dirham" all normalize to "AED". Returns `None`
    (rather than guessing) when the token isn't recognized — the caller
    should keep the raw text visible for the reviewer in that case."""
    if not text:
        return None
    key = normalize_whitespace(text)
    if key is None:
        return None
    return _CURRENCY_ALIASES.get(key.upper()) or _CURRENCY_ALIASES.get(key)


# --- Amounts / numeric formatting -------------------------------------------


@dataclass(frozen=True, slots=True)
class ParsedAmount:
    """The result of attempting to parse a numeric string.

    `ambiguous=True` means the format genuinely could be read two ways
    (e.g. "1,250" as either a thousands separator or a European decimal
    comma) and `value` is deliberately `None` — never a guess. `raw`
    preserves exactly what was passed in, for the raw-extraction layer.
    """

    value: Decimal | None
    ambiguous: bool
    raw: str


_NUMERIC_CHARS_RE = re.compile(r"[^0-9.,\-]")


def parse_amount(text: str) -> ParsedAmount:
    """Parse a monetary/numeric string into a `Decimal`, flagging genuine
    locale ambiguity instead of guessing. Any currency symbol/letters are
    stripped first — extract currency separately via
    `normalize_currency_token` if needed.
    """
    raw = text
    cleaned = _NUMERIC_CHARS_RE.sub("", text)
    if not cleaned or cleaned in {"-", "."}:
        return ParsedAmount(None, ambiguous=False, raw=raw)

    has_comma = "," in cleaned
    has_dot = "." in cleaned

    try:
        if has_comma and has_dot:
            if cleaned.rfind(",") > cleaned.rfind("."):
                decimal_sep, thousands_sep = ",", "."
            else:
                decimal_sep, thousands_sep = ".", ","
            normalized = cleaned.replace(thousands_sep, "")
            normalized = normalized.replace(decimal_sep, ".")
            return ParsedAmount(Decimal(normalized), ambiguous=False, raw=raw)

        if has_comma and not has_dot:
            groups = cleaned.split(",")
            last_group = groups[-1]
            if len(groups) == 2 and len(last_group) in (1, 2):
                # e.g. "1250,5" / "1250,00" — almost certainly a decimal comma.
                return ParsedAmount(Decimal(cleaned.replace(",", ".")), ambiguous=False, raw=raw)
            if len(groups) == 2 and len(last_group) == 3:
                # e.g. "1,250" — could be 1250 (thousands sep) or 1.250 (EU
                # decimal comma). Genuinely ambiguous without more context.
                return ParsedAmount(None, ambiguous=True, raw=raw)
            if all(len(g) == 3 for g in groups[1:]):
                # e.g. "1,234,567" — multiple 3-digit groups is unambiguously
                # a thousands separator.
                return ParsedAmount(Decimal(cleaned.replace(",", "")), ambiguous=False, raw=raw)
            return ParsedAmount(Decimal(cleaned.replace(",", "")), ambiguous=False, raw=raw)

        if has_dot and not has_comma:
            groups = cleaned.split(".")
            last_group = groups[-1]
            if len(groups) == 2 and len(last_group) in (1, 2):
                return ParsedAmount(Decimal(cleaned), ambiguous=False, raw=raw)
            if len(groups) == 2 and len(last_group) == 3:
                # e.g. "1.250" — could be 1250 (EU thousands sep) or 1.25.
                return ParsedAmount(None, ambiguous=True, raw=raw)
            if len(groups) > 2:
                return ParsedAmount(Decimal(cleaned.replace(".", "")), ambiguous=False, raw=raw)
            return ParsedAmount(Decimal(cleaned), ambiguous=False, raw=raw)

        return ParsedAmount(Decimal(cleaned), ambiguous=False, raw=raw)
    except InvalidOperation:
        return ParsedAmount(None, ambiguous=False, raw=raw)


# --- Dates --------------------------------------------------------------------

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%m/%d/%Y",
)


def parse_date_maybe(text: str | None) -> date | None:
    """Try a fixed set of common date formats, day-first where ambiguous
    (this business operates in the UAE, where day/month/year is the norm).
    Returns `None` — never a wrong guess — if nothing matches."""
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


# --- Units ----------------------------------------------------------------

_UNIT_ALIASES: dict[str, str] = {
    "SQM": "m2",
    "SQ.M": "m2",
    "SQ M": "m2",
    "M2": "m2",
    "M²": "m2",
    "LM": "lm",
    "L.M": "lm",
    "LIN.M": "lm",
    "NO": "nos",
    "NOS": "nos",
    "NO.": "nos",
    "EA": "ea",
    "EACH": "ea",
    "KG": "kg",
    "TON": "ton",
    "TONNE": "ton",
    "TONNES": "ton",
    "L": "l",
    "LTR": "l",
    "LITRE": "l",
}


def normalize_unit(text: str | None) -> str | None:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return None
    return _UNIT_ALIASES.get(cleaned.upper(), cleaned)


# --- Net / tax / gross reconciliation ---------------------------------------


@dataclass(frozen=True, slots=True)
class NetTaxGross:
    net: Decimal | None
    tax: Decimal | None
    gross: Decimal | None
    derived_field: str | None  # which field (if any) was filled in, not extracted


def reconcile_net_tax_gross(
    net: Decimal | None, tax: Decimal | None, gross: Decimal | None
) -> NetTaxGross:
    """If exactly one of net/tax/gross is missing and the other two are
    present, derive it — using the same `calculate_net_of_tax` /
    `calculate_gross_amount` pure functions the rest of the app uses, never
    a second copy of that arithmetic. If all three are present, they are
    left exactly as extracted (a mismatch is a review signal, not something
    this layer silently corrects).
    """
    present = sum(value is not None for value in (net, tax, gross))
    if present < 2:
        return NetTaxGross(net, tax, gross, derived_field=None)

    if net is None and tax is not None and gross is not None:
        return NetTaxGross(calculate_net_of_tax(gross, tax), tax, gross, derived_field="net")
    if gross is None and net is not None and tax is not None:
        return NetTaxGross(net, tax, calculate_gross_amount(net, tax), derived_field="gross")
    if tax is None and net is not None and gross is not None:
        return NetTaxGross(net, gross - net, gross, derived_field="tax")

    return NetTaxGross(net, tax, gross, derived_field=None)
