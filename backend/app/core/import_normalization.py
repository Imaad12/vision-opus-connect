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


# One numeric run: an optional leading minus sign, then digits with
# optional grouping/decimal separators (`,` or `.`) *between* digits only
# — this never matches across a gap of letters/spaces, so "5% charges SR
# 900.00" tokenizes as two separate runs ("5", "900.00") rather than one
# string that could be stripped-and-concatenated into "5900.00".
#
# The minus sign may be separated from its digits by up to a few spaces
# (a real OCR/typesetting artifact: "SR - 900.00" for a credit/discount
# line) — but only when it is NOT itself glued to a preceding word/digit
# character, via the negative lookbehind. Without that lookbehind, a
# hyphenated identifier like "Ref-2024" or "PO-2024" would be misread as
# the negative amount -2024; with it, the hyphen there is correctly left
# attached to the word, not treated as a sign, and "2024" tokenizes as a
# plain positive number instead.
#
# The sign character itself accepts the ASCII hyphen-minus plus two
# Unicode dash characters (EN DASH U+2013, MINUS SIGN U+2212) that a
# document/PDF renderer can legitimately use for a minus sign instead of
# the plain hyphen (found via adversarial testing: without this, "–150.00"
# silently became positive 150.00 — a sign lost, not merely a value
# rejected, exactly the dangerous failure mode already fixed once for the
# whitespace-separated ASCII case).
_SIGN_CHARS = "−–-"
_NUMERIC_TOKEN_RE = re.compile(rf"(?<![\w.])[{_SIGN_CHARS}]\s{{0,3}}\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*")

# A numeric token immediately (optionally via whitespace) followed by a
# percent sign is a rate, never a monetary amount — see the real-archive
# case this guards against: "VAT 5% charges SR 900.00" must extract the
# amount as 900.00, never as a number built from the "5" too.
_PERCENT_SUFFIX_RE = re.compile(r"\s*%")


def _parse_numeric_token(cleaned: str) -> ParsedAmount:
    """Parse one already-isolated numeric token (digits plus at most the
    separators between them — no currency letters, no stray words) into a
    `Decimal`, flagging genuine locale ambiguity instead of guessing."""
    raw = cleaned
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


def parse_amount(text: str) -> ParsedAmount:
    """Parse a monetary/numeric string into a `Decimal`, flagging genuine
    locale ambiguity instead of guessing. Any currency symbol/letters are
    ignored — extract currency separately via `normalize_currency_token`
    if needed.

    Deliberately tokenizes first rather than stripping every non-numeric
    character from the whole string and parsing what's left as one
    number: a real archive document produced "VAT : 5% charges SR
    900.00", and the naive strip-everything approach silently concatenated
    the "5" from "5%" onto "900.00" into a fabricated 5,900.00 — a
    confidently-wrong financial value. Percentage/rate numbers (a numeric
    token directly followed by `%`) are never treated as the monetary
    amount. If more than one genuine amount-shaped token remains after
    excluding percentages, which one is "the" value is genuinely
    ambiguous and must not be guessed.
    """
    raw = text
    amount_tokens: list[str] = []
    for match in _NUMERIC_TOKEN_RE.finditer(text):
        token = re.sub(r"\s", "", match.group())  # collapse "- 900.00" -> "-900.00"
        if token and token[0] in _SIGN_CHARS:
            # Normalize any accepted sign character to the ASCII hyphen
            # `Decimal(...)` actually understands -- "−150.00"/"–150.00"
            # must parse the same way "-150.00" already does, not raise.
            token = "-" + token[1:]
        if token in {"-", "."}:
            continue
        if _PERCENT_SUFFIX_RE.match(text, match.end()):
            continue  # a rate (e.g. "5%"), never a monetary amount
        amount_tokens.append(token)

    if not amount_tokens:
        return ParsedAmount(None, ambiguous=False, raw=raw)
    if len(amount_tokens) > 1:
        # More than one candidate monetary figure on the same line/cell
        # (and not distinguishable as a rate) — which one is the real
        # amount is genuinely ambiguous; never guess.
        return ParsedAmount(None, ambiguous=True, raw=raw)

    result = _parse_numeric_token(amount_tokens[0])
    return ParsedAmount(result.value, result.ambiguous, raw=raw)


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
    # Real client PO wording ("PO Date : 15-May-26") -- day, hyphen,
    # abbreviated month, hyphen, 2-digit year. Not previously needed by
    # any quotation in the real archive (which always prints a 4-digit
    # year), but genuinely used by at least one real client's own PO
    # template. `%y` follows Python's standard POSIX-style pivot
    # (00-68 -> 2000-2068), which is correct for this business's date
    # range and requires no extra logic.
    "%d-%b-%y",
)


# A real, recurring real-archive OCR artifact: dates print with the
# sentence-ending punctuation from the source line still attached (e.g.
# "Nov 19, 2018.", "Date: November 20, 2018."), which `strptime`'s exact
# matching rejects outright even though the date itself was read
# perfectly -- the label was already found (HIGH/LOW confidence shows a
# match), only the trailing character defeats the parse. This is narrow
# by design: it only ever strips characters that can never appear inside
# a real date value itself (a period, colon, or semicolon are never part
# of a day/month/year token in any of `_DATE_FORMATS`), and only from the
# very end of the string -- it does not touch a comma that is already
# part of "Month DD, YYYY", since that comma is never trailing. It never
# broadens which formats are accepted or guesses a date that doesn't
# otherwise match one of them exactly.
#
# `|` is included alongside them for the same reason -- a real, observed
# table/box-drawing artifact landing right after the date (real:
# "Date : Aug 28,2018. |") -- and whitespace is included in the class
# itself (not just trimmed by the `.strip()` below) so a run mixing
# harmless punctuation *and* whitespace before the true end (here, the
# period, then a space, then the stray "|") is stripped in one pass
# rather than leaving an inner character the single non-iterative pass
# could not reach.
_TRAILING_HARMLESS_PUNCTUATION_RE = re.compile(r"[\s.:;|]+$")

# Two more real, recurring archive OCR artifacts around the comma in
# "Month DD, YYYY" -- confirmed directly against the real archive's date
# lines, both distinct from the trailing-punctuation case above and from
# each other: a space *before* the comma ("November 18 , 2018.", real
# page 14) and no space *after* it ("November 29,2018.", real pages
# 19/21/22 -- the more common of the two, confirmed on three separate
# real documents). Both are pure whitespace differences around a comma
# that is already exactly where `_DATE_FORMATS`'s "%B %d, %Y"/"%b %d, %Y"
# expect it -- normalizing any whitespace around that comma to exactly
# ", " never touches a day/month/year digit or word, and reuses the
# existing format strings unchanged rather than adding new ones.
_DATE_COMMA_SPACING_RE = re.compile(r"\s*,\s*")


def parse_date_maybe(text: str | None) -> date | None:
    """Try a fixed set of common date formats, day-first where ambiguous
    (this business operates in the UAE, where day/month/year is the norm).
    Tolerates harmless trailing punctuation and comma-spacing left over
    from OCR (see `_TRAILING_HARMLESS_PUNCTUATION_RE` and
    `_DATE_COMMA_SPACING_RE`) without changing the parsed date itself.
    Returns `None` — never a wrong guess — if nothing matches."""
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return None
    candidates = [cleaned]
    stripped = _TRAILING_HARMLESS_PUNCTUATION_RE.sub("", cleaned).strip()
    if stripped and stripped != cleaned:
        candidates.append(stripped)
    for base in list(candidates):
        comma_normalized = _DATE_COMMA_SPACING_RE.sub(", ", base)
        if comma_normalized not in candidates:
            candidates.append(comma_normalized)
    for candidate in candidates:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date()
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
