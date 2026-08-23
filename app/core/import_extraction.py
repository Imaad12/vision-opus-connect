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


# --- Quotation field scanning ------------------------------------------------

_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "quotation_number": ("quotation no", "quotation number", "quote no", "quote number", "reference no", "reference number", "ref no"),
    "quotation_date": ("quotation date", "quote date", "date"),
    "client_name": ("client name", "client", "customer name", "customer", "bill to", "attn"),
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


def _pattern_for(label: str) -> re.Pattern[str]:
    if label not in _LINE_PATTERN_CACHE:
        escaped = re.escape(label)
        _LINE_PATTERN_CACHE[label] = re.compile(rf"^\s*{escaped}\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)
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

    return ExtractionResult(quotation=quotation, boq_rows=boq_rows, document_kind=kind)
