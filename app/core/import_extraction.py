"""Deterministic candidate extraction: turns a `RawExtraction` (what a
parser found) into reviewable quotation/BOQ candidate data (what the
application believes those values represent).

This is the "NORMALIZED CANDIDATE DATA" layer described in
IMPORT_ARCHITECTURE.md — it never writes to the database, never decides a
value is final, and never runs any AI/ML model. It is pattern matching and
arithmetic only (reusing `app.core.financial_engine`'s pure functions,
never re-deriving them), exactly like the rest of `app.core`.

Confidence is deliberately categorical (`ConfidenceLevel`), not a
percentage — see `app.core.enums.ConfidenceLevel` and
IMPORT_ARCHITECTURE.md §8 for why a fabricated "98% confidence" would be
worse than no confidence figure at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.enums import ConfidenceLevel, ImportDocumentKind
from app.core.financial_engine import calculate_line_total
from app.core.import_normalization import (
    normalize_currency_token,
    normalize_unit,
    normalize_whitespace,
    parse_amount,
    parse_date_maybe,
    reconcile_net_tax_gross,
)
from app.importers.base import ExtractedTable, RawExtraction

# A material mismatch between an extracted amount and quantity * unit_rate:
# larger than 1% of the extracted amount, or more than 1 currency unit,
# whichever is bigger (covers both large-value rounding and tiny amounts).
_AMOUNT_TOLERANCE_FRACTION = Decimal("0.01")
_AMOUNT_TOLERANCE_FLOOR = Decimal("1")


@dataclass
class QuotationCandidateFields:
    quotation_number: str | None = None
    quotation_date: date | None = None
    client_name: str | None = None
    project_name: str | None = None
    project_number: str | None = None
    description: str | None = None
    currency: str | None = None
    net_value: Decimal | None = None
    tax_value: Decimal | None = None
    gross_value: Decimal | None = None
    valid_until: date | None = None
    payment_terms: str | None = None
    notes: str | None = None
    raw_values: dict[str, str] = field(default_factory=dict)
    field_confidence: dict[str, str] = field(default_factory=dict)


@dataclass
class BoqRowCandidate:
    group_label: str | None
    row_order: int
    item_number: str | None = None
    description: str | None = None
    category_label: str | None = None
    unit: str | None = None
    quantity: Decimal | None = None
    unit_rate: Decimal | None = None
    extracted_amount: Decimal | None = None
    calculated_amount: Decimal | None = None
    amount_flagged: bool = False
    notes: str | None = None


@dataclass
class ExtractionResult:
    quotation: QuotationCandidateFields
    boq_rows: list[BoqRowCandidate]
    document_kind: ImportDocumentKind
    #: Distinct quotation reference strings found anywhere in the source
    #: (see `find_distinct_quotation_references`). Length > 1 means this
    #: staged file appears to bundle more than one independent quotation
    #: document — the caller (`app.services.import_service.run_extraction`)
    #: must not build a single candidate from it in that case.
    distinct_references: list[str] = field(default_factory=list)
    #: Distinct *parsed* quotation dates found anywhere in the source (see
    #: `find_distinct_quotation_dates`) — a second, independent signal for
    #: the same "more than one document in this file" check, needed
    #: because a real archive scan can lose the reference label on one
    #: page while its date survives (or vice versa on another page).
    distinct_dates: list[date] = field(default_factory=list)


# --- Quotation field scanning ------------------------------------------------

_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    # "reference"/"quotation reference" are deliberately the lowest-priority
    # (shortest/least specific) labels here -- confirmed from real archive
    # documents that print bare "Reference:" or "Quotation Reference:" for
    # their own quotation number. Sorted after the more specific labels
    # below (see `_FIELD_ORDER`), so a document that also has an unrelated
    # "Reference: <correspondence note>" line elsewhere is only matched by
    # bare "reference" if nothing more specific was found first -- a known,
    # accepted trade-off (the same shape as "attn" already being accepted
    # for `client_name` even though it sometimes captures a person's name).
    "quotation_number": (
        "quotation no",
        "quotation number",
        "quote no",
        "quote number",
        "reference no",
        "reference number",
        "ref no",
        "quotation reference",
        "reference",
    ),
    "quotation_date": ("quotation date", "quote date", "date"),
    # "kind attn" (before bare "attn") is the real Vinco archive's own
    # wording for every single quotation that uses this label at all
    # ("Kind Attn. : Mr. Syed Nazir Ali", "Kind Attn. - Mr. Nelson") --
    # confirmed against the real archive's saved OCR output, where bare
    # "Attn" never once appears at the start of a line unprefixed. Without
    # this, `client_name` was never populated from any of these real
    # documents despite "attn" already being a recognized label.
    "client_name": ("client name", "kind attn", "client", "customer name", "customer", "bill to", "attn"),
    "project_name": ("project name", "project title", "project"),
    "project_number": ("project no", "project number", "project code"),
    "description": ("scope of work", "description", "scope"),
    "currency": ("currency",),
    "net_value": ("net amount", "net value", "amount excluding vat", "total excluding vat", "net total", "subtotal", "sub total"),
    "tax_value": ("vat amount", "vat @ 5%", "vat", "tax amount", "tax"),
    "gross_value": ("total including vat", "grand total", "total amount", "total value", "gross amount", "gross value", "total"),
    "valid_until": ("quotation valid until", "valid until", "valid till", "validity"),
    "payment_terms": ("payment terms", "terms of payment"),
}

# Longer/more specific labels must be tried before shorter ones that would
# also match them (e.g. "total including vat" before "total").
_FIELD_ORDER = sorted(
    ((field_name, label) for field_name, labels in _FIELD_LABELS.items() for label in labels),
    key=lambda pair: -len(pair[1]),
)

_LINE_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}

# VAT wording classification -- used only to decide *why* `tax_value`
# ended up unset after the normal label scan above, never to change
# whether/how a field is matched. Both patterns are grounded in real
# archive wording (see IMPORT_ARCHITECTURE.md for the source quotations):
#
#   - "VAT inclusive" style wording ("prices are inclusive of VAT") means
#     a separate VAT line is not expected at all -- the printed total
#     already includes it. No real archive document was found using this
#     wording (none of Vinco's own quotations state it), but the business
#     rule below must still not conflate this state with "OCR simply
#     failed to find VAT" if a future document does use it.
#   - "VAT excluded, no absolute amount" wording ("VAT 5% not included in
#     our offer", "5% VAT will be charged extra") is common in the real
#     archive -- these quotations genuinely do not print a SAR VAT figure
#     anywhere, only a rate/disclaimer, so no amount is determinable
#     without inventing one from the stated rate (which this module must
#     never do -- see `_apply_vat_determination_when_undetermined`).
_VAT_INCLUSIVE_PATTERN = re.compile(
    r"vat\s+inclusive|inclusive\s+of\s+vat|includ\w*\s+vat|vat\s+includ\w*",
    re.IGNORECASE,
)
_VAT_EXCLUDED_NO_AMOUNT_PATTERN = re.compile(
    r"vat[^\n]{0,40}(?:not\s+includ|will\s+be\s+charged\s+extra|excluded|extra)",
    re.IGNORECASE,
)


def _apply_vat_determination_when_undetermined(result: QuotationCandidateFields, text: str | None) -> None:
    """Called only when `tax_value` is still `None` after both the normal
    label scan and `reconcile_net_tax_gross`'s algebraic derivation --
    i.e. no VAT amount could be read from this document by any existing
    means. Implements the explicit business rule: "if VAT is genuinely
    not determinable, VAT = SAR 0.00 -- never assume 15%, never invent an
    amount." This never computes a VAT figure from a stated rate (e.g.
    "5%"); it only ever records the fixed SAR 0.00 the business rule
    specifies, or leaves the field alone for the VAT-inclusive case.

    Tags *why* in `raw_values["tax_value_basis"]` (already a persisted,
    schema-free JSON field -- no new column needed) so "VAT-inclusive, no
    separate line expected" and "genuinely undeterminable, 0.00 applied
    per business rule" remain distinguishable internal states, never
    conflated, even though only the second one changes `tax_value`.
    """
    full_text = text or ""
    if _VAT_INCLUSIVE_PATTERN.search(full_text):
        # A separate VAT figure is not expected on this document at all --
        # the printed total already includes it. Do not fabricate a VAT
        # amount by assuming a rate, and do not apply the "0.00" business
        # rule here either: that rule is for "not determinable", not for
        # "determined to be embedded in the total".
        result.raw_values["tax_value_basis"] = "vat_inclusive"
        return

    result.raw_values["tax_value_basis"] = "undetermined_zero_applied"
    excluded_match = _VAT_EXCLUDED_NO_AMOUNT_PATTERN.search(full_text)
    if excluded_match:
        result.raw_values["tax_value_note"] = normalize_whitespace(excluded_match.group(0)) or ""
    result.tax_value = Decimal("0.00")
    result.field_confidence["tax_value"] = ConfidenceLevel.LOW.value


def _pattern_for(label: str) -> re.Pattern[str]:
    if label not in _LINE_PATTERN_CACHE:
        escaped = re.escape(label)
        # `»` is included alongside `:`/`-` because real-archive OCR output
        # (Tesseract, real Vinco scans) was observed to misread a printed
        # colon as `»` specifically ("Reference » VN/QU/412/18"). This is a
        # narrow, specific substitution for one confirmed OCR artifact --
        # not a general "any separator" relaxation, so it doesn't make
        # label matching any more permissive about what counts as a label.
        # `|` is included because a BOQ totals row rendered through OCR
        # commonly comes out as a table cell boundary rather than a colon
        # (real archive: "Total (SAR) | 51,644.77") -- same narrow,
        # single-character-class reasoning as `»`.
        #
        # An optional parenthetical currency/unit annotation is allowed
        # between the label and the separator (e.g. "Total (SAR) |
        # 51,644.77", "Sub Total (SAR) | 49,185.50") -- confirmed from the
        # same real archive totals rows, where the currency is printed as
        # part of the label's own table header rather than the value.
        #
        # An optional trailing "." directly after the label is allowed
        # (real archive: "Kind Attn." is always printed with the period,
        # never bare "Kind Attn") -- narrow, and only ever consumed right
        # after the label itself, so it cannot let the separator check
        # below become any more permissive.
        #
        # The separator itself may be one *or more* of `:`/`-`/`»`/`|`/`—`
        # (an em dash is included alongside `-` for the same reason as
        # `»`: a real, observed OCR misread), each optionally followed by
        # whitespace -- because the real archive was found to sometimes
        # print a doubled separator ("Kind Attn. — : Mr. Nelson,"). This
        # still always requires at least one real separator character; it
        # only tolerates more than one appearing together.
        #
        # Bare whitespace is deliberately NOT accepted as a separator: that
        # would match "Reference Section 3.2 discusses..." just as readily
        # as an actual label:value line, which is exactly the over-broad
        # matching this project's label-based extraction must avoid.
        _LINE_PATTERN_CACHE[label] = re.compile(
            rf"^\s*{escaped}\.?\s*(?:\([^)]{{0,20}}\)\s*)?(?:[:\-»|—]\s*)+(.+?)\s*$", re.IGNORECASE
        )
    return _LINE_PATTERN_CACHE[label]


def _candidate_lines(text: str | None, tables: list[ExtractedTable]) -> list[str]:
    lines: list[str] = []
    if text:
        lines.extend(text.splitlines())
    for table in tables:
        for row in table.rows:
            if len(row) >= 2 and row[0].strip():
                # A "Label: Value" style row spread across two cells, common
                # in quotation header blocks inside a spreadsheet.
                lines.append(f"{row[0].strip()}: {' '.join(c for c in row[1:] if c.strip())}")
    return lines


def extract_quotation_candidate(text: str | None, tables: list[ExtractedTable]) -> QuotationCandidateFields:
    result = QuotationCandidateFields()
    lines = _candidate_lines(text, tables)
    found: set[str] = set()

    for field_name, label in _FIELD_ORDER:
        if field_name in found:
            continue
        pattern = _pattern_for(label)
        for line in lines:
            match = pattern.match(line)
            if not match:
                continue
            raw_value = normalize_whitespace(match.group(1))
            if not raw_value:
                continue
            _apply_field(result, field_name, raw_value)
            found.add(field_name)
            break

    net, tax, gross = result.net_value, result.tax_value, result.gross_value
    reconciled = reconcile_net_tax_gross(net, tax, gross)
    if reconciled.derived_field == "net":
        result.net_value = reconciled.net
        result.field_confidence["net_value"] = ConfidenceLevel.NEEDS_REVIEW.value
    elif reconciled.derived_field == "tax":
        result.tax_value = reconciled.tax
        result.field_confidence["tax_value"] = ConfidenceLevel.NEEDS_REVIEW.value
    elif reconciled.derived_field == "gross":
        result.gross_value = reconciled.gross
        result.field_confidence["gross_value"] = ConfidenceLevel.NEEDS_REVIEW.value

    if result.tax_value is None:
        _apply_vat_determination_when_undetermined(result, text)

    return result


def _apply_field(result: QuotationCandidateFields, field_name: str, raw_value: str) -> None:
    result.raw_values[field_name] = raw_value

    if field_name in ("quotation_date", "valid_until"):
        parsed_date = parse_date_maybe(raw_value)
        setattr(result, field_name, parsed_date)
        result.field_confidence[field_name] = (
            ConfidenceLevel.HIGH.value if parsed_date else ConfidenceLevel.LOW.value
        )
        return

    if field_name in ("net_value", "tax_value", "gross_value"):
        currency_token = normalize_currency_token(raw_value)
        if currency_token and result.currency is None:
            result.currency = currency_token
        parsed = parse_amount(raw_value)
        setattr(result, field_name, parsed.value)
        if parsed.ambiguous:
            result.field_confidence[field_name] = ConfidenceLevel.LOW.value
        elif parsed.value is not None:
            result.field_confidence[field_name] = ConfidenceLevel.HIGH.value
        else:
            result.field_confidence[field_name] = ConfidenceLevel.LOW.value
        return

    if field_name == "currency":
        token = normalize_currency_token(raw_value)
        result.currency = token or raw_value
        result.field_confidence[field_name] = (
            ConfidenceLevel.HIGH.value if token else ConfidenceLevel.NEEDS_REVIEW.value
        )
        return

    setattr(result, field_name, raw_value)
    result.field_confidence[field_name] = ConfidenceLevel.HIGH.value


def _find_distinct_labeled_values(field_name: str, text: str | None, tables: list[ExtractedTable]) -> list[str]:
    """Scan for every line matching any label for `field_name` (not just
    the first, unlike `extract_quotation_candidate`), returning the
    distinct non-empty captured raw strings in the order first seen.

    This exists solely so the caller can detect "this one staged file
    appears to contain more than one quotation document" and refuse to
    build one spliced candidate from it — it is never used to pick which
    value "wins" for a real field. No document-segmentation or
    per-quotation parsing is attempted; this only counts distinct raw
    strings for one field.
    """
    lines = _candidate_lines(text, tables)
    labels = _FIELD_LABELS[field_name]
    seen: list[str] = []
    for label in labels:
        pattern = _pattern_for(label)
        for line in lines:
            match = pattern.match(line)
            if not match:
                continue
            value = normalize_whitespace(match.group(1))
            if value and value not in seen:
                seen.append(value)
    return seen


def find_distinct_quotation_references(text: str | None, tables: list[ExtractedTable]) -> list[str]:
    """Distinct quotation-reference strings anywhere in the source — see
    `_find_distinct_labeled_values`. Length > 1 is strong evidence this
    staged file bundles more than one quotation document (a real,
    demonstrated risk for multi-page scanned archives — a single 24-page
    scan can bundle 16+ independent quotations)."""
    return _find_distinct_labeled_values("quotation_number", text, tables)


def find_distinct_quotation_dates(text: str | None, tables: list[ExtractedTable]) -> list[date]:
    """Distinct *parsed* quotation dates anywhere in the source.

    A single quotation document only ever has one issue date. This is a
    second, independent signal for "more than one document in this file"
    alongside `find_distinct_quotation_references` — needed because a
    real archive scan can lose the reference label on one page while its
    date line survives intact (and vice versa on another page): reference
    counting alone missed that case (traced and confirmed against the
    real archive during the adversarial safety review — a candidate could
    otherwise splice one document's reference/date onto a different
    document's net value, both with HIGH field confidence, with nothing
    to catch it). Raw strings that fail to parse into a real date are
    excluded — unparseable text is not reliable evidence either way.
    """
    raw_values = _find_distinct_labeled_values("quotation_date", text, tables)
    seen_dates: list[date] = []
    for raw_value in raw_values:
        parsed = parse_date_maybe(raw_value)
        if parsed is not None and parsed not in seen_dates:
            seen_dates.append(parsed)
    return seen_dates


# --- BOQ row scanning ---------------------------------------------------------

_HEADER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "item_number": ("item", "item no", "item no.", "s.no", "sr.no", "sl.no"),
    "description": ("description", "particulars", "item description"),
    "category_label": ("trade", "category", "category/trade", "cost category"),
    "unit": ("unit", "uom", "u.o.m"),
    "quantity": ("qty", "quantity", "qnty"),
    "unit_rate": ("rate", "unit rate", "unit price"),
    "extracted_amount": ("amount", "total", "total amount", "total price", "value"),
}


def _match_header(cell: str) -> str | None:
    normalized = (normalize_whitespace(cell) or "").lower().rstrip(".")
    for column, keywords in _HEADER_KEYWORDS.items():
        if normalized in keywords:
            return column
    return None


def _find_header_row(rows: list[list[str]]) -> tuple[int, dict[int, str]] | None:
    for row_index, row in enumerate(rows):
        columns: dict[int, str] = {}
        for col_index, cell in enumerate(row):
            match = _match_header(cell)
            if match:
                columns[col_index] = match
        has_description = "description" in columns.values()
        has_numeric_column = any(
            col in columns.values() for col in ("quantity", "unit_rate", "extracted_amount")
        )
        if has_description and has_numeric_column:
            return row_index, columns
    return None


def extract_boq_rows(tables: list[ExtractedTable]) -> list[BoqRowCandidate]:
    candidates: list[BoqRowCandidate] = []
    row_order = 0

    for table in tables:
        header = _find_header_row(table.rows)
        if header is None:
            continue
        header_row_index, columns = header

        for row in table.rows[header_row_index + 1 :]:
            if not any(cell.strip() for cell in row):
                continue

            def cell(column_name: str) -> str | None:
                for col_index, mapped_name in columns.items():
                    if mapped_name == column_name and col_index < len(row):
                        value = normalize_whitespace(row[col_index])
                        return value
                return None

            description = cell("description")
            if not description:
                continue

            quantity_raw = cell("quantity")
            rate_raw = cell("unit_rate")
            amount_raw = cell("extracted_amount")

            quantity = parse_amount(quantity_raw).value if quantity_raw else None
            unit_rate = parse_amount(rate_raw).value if rate_raw else None
            extracted_amount = parse_amount(amount_raw).value if amount_raw else None
            calculated_amount = calculate_line_total(quantity, unit_rate)

            flagged = False
            if extracted_amount is not None and calculated_amount is not None:
                difference = abs(extracted_amount - calculated_amount)
                tolerance = max(_AMOUNT_TOLERANCE_FLOOR, abs(extracted_amount) * _AMOUNT_TOLERANCE_FRACTION)
                flagged = difference > tolerance

            candidates.append(
                BoqRowCandidate(
                    group_label=table.name,
                    row_order=row_order,
                    item_number=cell("item_number"),
                    description=description,
                    category_label=cell("category_label"),
                    unit=normalize_unit(cell("unit")),
                    quantity=quantity,
                    unit_rate=unit_rate,
                    extracted_amount=extracted_amount,
                    calculated_amount=calculated_amount,
                    amount_flagged=flagged,
                )
            )
            row_order += 1

    return candidates


# --- Top-level entry point ----------------------------------------------------


def extract_candidates(raw: RawExtraction) -> ExtractionResult:
    quotation = extract_quotation_candidate(raw.text, raw.tables)
    boq_rows = extract_boq_rows(raw.tables)
    distinct_references = find_distinct_quotation_references(raw.text, raw.tables)
    distinct_dates = find_distinct_quotation_dates(raw.text, raw.tables)

    has_quotation_data = any(
        getattr(quotation, name) is not None
        for name in (
            "quotation_number",
            "client_name",
            "project_name",
            "project_number",
            "net_value",
            "gross_value",
        )
    )
    if has_quotation_data:
        kind = ImportDocumentKind.QUOTATION
    elif boq_rows:
        kind = ImportDocumentKind.BOQ
    else:
        kind = ImportDocumentKind.UNKNOWN

    return ExtractionResult(
        quotation=quotation,
        boq_rows=boq_rows,
        document_kind=kind,
        distinct_references=distinct_references,
        distinct_dates=distinct_dates,
    )
