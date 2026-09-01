"""Deterministic Purchase Order field extraction (PO ingestion foundation).

Mirrors `app.core.import_extraction`'s quotation extraction deliberately —
same categorical `ConfidenceLevel`, same "Label: Value" line-scanning
approach, same pure-function reconciliation — reusing its proven
`_candidate_lines`/`_pattern_for` helpers directly rather than
duplicating the regex/line-matching machinery. Quotation extraction
itself is not modified by this module (see PO_ARCHITECTURE.md, task
constraint: "do not touch quotation OCR extraction unless absolutely
required").

Scope is deliberately small: the business's real PO archive has not yet
been ingested, so — unlike `import_extraction.py`'s quotation label set,
which was refined across four rounds against real scanned documents —
these label lists are provisional and generic accounting-document
vocabulary, not yet evidence-tuned. Only fields with a clear, immediate
analytics/business use are extracted at all; nothing is invented "in case
it's useful later" (see the task's "do not invent fields that cannot be
reliably supported" constraint). No BOQ-style line-item extraction and no
multi-PO-per-file segmentation are attempted this round — a real PO is
assumed to be one document, one PO (see `PO_ARCHITECTURE.md`); revisiting
that is future work once real PO scans exist to test against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.enums import ConfidenceLevel
from app.core.import_extraction import _candidate_lines, _pattern_for
from app.core.import_normalization import (
    normalize_currency_token,
    normalize_whitespace,
    parse_amount,
    parse_date_maybe,
    reconcile_net_tax_gross,
)
from app.importers.base import ExtractedTable


@dataclass
class ClientAwardEvidenceCandidateFields:
    po_reference_number: str | None = None
    po_date: date | None = None
    currency: str | None = None
    net_value: Decimal | None = None
    tax_value: Decimal | None = None
    gross_value: Decimal | None = None
    raw_values: dict[str, str] = field(default_factory=dict)
    field_confidence: dict[str, str] = field(default_factory=dict)


# "po_reference_number" is, per current business practice, the *quotation's*
# own reference number as printed on the PO -- there is no separate
# PO-internal numbering scheme in scope for this foundation (see module
# docstring). Its label set therefore mirrors the quotation side's own
# "bare reference" wording (`import_extraction._FIELD_LABELS["quotation_number"]`)
# plus a few PO-specific phrasings a client might reasonably use to cite
# the quotation being ordered against. Provisional pending a real PO
# archive to validate against -- not yet evidence-tuned the way the
# quotation label set is.
_PO_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "po_reference_number": (
        "quotation reference number",
        "quotation reference",
        # "Quotation Ref." -- the abbreviated form -- is real, demonstrated
        # wording from an actual client PO template (Eastern Agriculture
        # Company), distinct from the already-present unabbreviated
        # "quotation reference" above.
        "quotation ref",
        "quotation number",
        "quotation no",
        "against quotation no",
        "against quotation",
        # Real wording from two independent client PO templates (Saudi
        # Power Transformers Co., WAHAH Electric Supply Co.) -- both use
        # this exact phrase, with a table-cell separator (":"/"|"), for
        # the field that cites the quotation being ordered against.
        "your/vendor ref",
        "our reference",
        "reference no",
        "reference number",
        "ref no",
        "reference",
    ),
    "po_date": ("po date", "order date", "date"),
    "currency": ("currency",),
    "net_value": ("net amount", "net value", "amount excluding vat", "po value", "order value", "subtotal", "sub total"),
    "tax_value": ("vat amount", "vat", "tax amount", "tax"),
    "gross_value": ("total including vat", "grand total", "total amount", "total value", "gross amount", "total"),
}

_PO_FIELD_ORDER = sorted(
    ((field_name, label) for field_name, labels in _PO_FIELD_LABELS.items() for label in labels),
    key=lambda pair: -len(pair[1]),
)

# Real client PO wording (confirmed against an actual client-issued PO,
# not invented): a two-column PO header table gets flattened into single
# OCR lines with the left column's leftover text still attached before
# the right column's own label -- e.g. "PO. Box-105 Quotation Ref. :
# PQ-SRF-2025-176" (the supplier address column bleeding into the
# "Quotation Ref." column). `_pattern_for`'s patterns are anchored to the
# start of the line by design (see its own docstring on why bare
# proximity must never be trusted), so this can never match there. This
# is a narrow, `search()`-based fallback used only when the normal
# anchored scan found nothing for `po_reference_number` -- deliberately
# scoped to specific multi-word phrases only (each containing "quotation",
# or the exact "your/vendor ref" wording confirmed on two independent real
# client PO templates), never a bare "reference"/"ref", to keep the
# false-positive surface small: unlike a bare "reference", none of these
# phrases is likely to occur as ordinary PO prose.
#
# Known, accepted limitation: this only recovers a label and value that
# remain on the *same* OCR line (the left column's leftover text merely
# prepended before the right column's label). A real client PO template
# (Saudi Power Transformers Co., real archive) uses this same
# "Your/Vendor Ref." label but its value ends up many lines away after
# OCR -- a genuine table reading-order scramble, not a same-line bleed --
# and is not recoverable by this or any other narrow, per-label fix; see
# PO_ARCHITECTURE.md.
_PO_REFERENCE_ANYWHERE_LABELS = (
    "quotation reference number",
    "quotation reference",
    "quotation ref",
    "quotation number",
    "quotation no",
    "against quotation no",
    "against quotation",
    "your/vendor ref",
)
_PO_REFERENCE_ANYWHERE_PATTERNS = [
    re.compile(
        rf"{re.escape(label)}\.?\s*(?:[:\-»|—>=]\s*)+(.+?)\s*$",
        re.IGNORECASE,
    )
    for label in sorted(_PO_REFERENCE_ANYWHERE_LABELS, key=len, reverse=True)
]


def _find_po_reference_anywhere_on_line(text: str | None, tables: list[ExtractedTable]) -> str | None:
    for line in _candidate_lines(text, tables):
        for pattern in _PO_REFERENCE_ANYWHERE_PATTERNS:
            match = pattern.search(line)
            if match:
                return match.group(1)
    return None


# Same real document: VAT and grand-total lines with no separator
# character between the label and the amount at all -- "Vat 15%
# 73500.00" and "Grand Total (SAR)} 563,500.00" (the "}" is a real OCR
# misread of the closing parenthesis/table border). This is the identical
# shape already handled on the quotation side
# (`import_extraction._VAT_LABEL_THEN_RATE_PATTERN`) -- duplicated here
# rather than imported, since it is PO-specific fallback wiring, not a
# change to quotation extraction itself. Fallback-only: never overrides a
# value already found by the normal labeled scan.
_PO_VAT_LABEL_THEN_RATE_PATTERN = re.compile(
    r"^\s*vat\s*@?\s*\d{1,2}(?:\.\d+)?\s*%\s+.*?([\d,]+\.\d{2})\s*$", re.IGNORECASE
)
_PO_GRAND_TOTAL_NO_SEPARATOR_PATTERN = re.compile(
    r"^\s*grand\s+total\s*(?:\([^)]{0,10}\))?\s*[}\)]?\s*([\d,]+\.\d{2})\s*$", re.IGNORECASE
)


def _find_po_vat_amount_without_separator(text: str | None, tables: list[ExtractedTable]) -> str | None:
    for line in _candidate_lines(text, tables):
        match = _PO_VAT_LABEL_THEN_RATE_PATTERN.match(line)
        if match:
            return match.group(1)
    return None


def _find_po_grand_total_without_separator(text: str | None, tables: list[ExtractedTable]) -> str | None:
    for line in _candidate_lines(text, tables):
        match = _PO_GRAND_TOTAL_NO_SEPARATOR_PATTERN.match(line)
        if match:
            return match.group(1)
    return None


def _apply_field(result: ClientAwardEvidenceCandidateFields, field_name: str, raw_value: str) -> None:
    result.raw_values[field_name] = raw_value

    if field_name == "po_date":
        parsed_date = parse_date_maybe(raw_value)
        result.po_date = parsed_date
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


def extract_client_award_evidence_candidate(
    text: str | None, tables: list[ExtractedTable]
) -> ClientAwardEvidenceCandidateFields:
    """Scan `text`/`tables` for PO-shaped fields using the same
    first-match-wins, longer-label-first discipline as
    `import_extraction.extract_quotation_candidate`. Purely deterministic
    pattern matching and arithmetic -- no AI/ML model, matching this
    project's project-wide rule that no financial figure is ever
    determined by a language model."""
    result = ClientAwardEvidenceCandidateFields()
    lines = _candidate_lines(text, tables)
    found: set[str] = set()

    for field_name, label in _PO_FIELD_ORDER:
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

    if result.po_reference_number is None:
        reference_anywhere = _find_po_reference_anywhere_on_line(text, tables)
        if reference_anywhere is not None:
            normalized = normalize_whitespace(reference_anywhere)
            if normalized:
                _apply_field(result, "po_reference_number", normalized)

    if result.tax_value is None:
        vat_anywhere = _find_po_vat_amount_without_separator(text, tables)
        if vat_anywhere is not None:
            _apply_field(result, "tax_value", vat_anywhere)

    if result.gross_value is None:
        grand_total_anywhere = _find_po_grand_total_without_separator(text, tables)
        if grand_total_anywhere is not None:
            _apply_field(result, "gross_value", grand_total_anywhere)

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


__all__ = ["ClientAwardEvidenceCandidateFields", "extract_client_award_evidence_candidate"]
