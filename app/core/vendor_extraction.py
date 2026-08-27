"""Deterministic vendor/supplier identity field extraction.

Deliberately document-type-agnostic: this module extracts a vendor's
*identity* (name, VAT/tax registration number) from a slice of already-OCR'd
text/tables, exactly like `app.core.po_extraction` extracts PO-shaped
fields — it has no idea whether the document it was handed is a client PO
that happens to name a nominated subcontractor, a future vendor-issued PO,
or a future vendor invoice. Nothing here is wired to any one document
kind; `app.services.import_service` decides *when* to call this, this
module only decides *what a vendor-identity line looks like*.

Reuses `app.core.import_extraction`'s proven `_candidate_lines`/
`_pattern_for` line-scanning machinery directly, the same way
`po_extraction.py` already does, rather than duplicating it.

Scope is deliberately small and provisional, per the project's own
established discipline (see `po_extraction.py`'s own module docstring):
no real supplier/vendor document archive has been ingested yet, so this
label set is generic accounting-document vocabulary, not yet
evidence-tuned. Only the two fields `app.services.vendor_matching`
actually uses for deterministic matching are extracted — nothing is
invented "in case it's useful later." When real supplier documents
become available, extend this label set the same way the quotation/PO
label sets were extended: diagnose against the real OCR output first,
then make a narrow, evidence-grounded addition with a regression test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import ConfidenceLevel
from app.core.import_extraction import _candidate_lines, _pattern_for
from app.core.import_normalization import normalize_whitespace
from app.importers.base import ExtractedTable


@dataclass
class VendorCandidateFields:
    vendor_name: str | None = None
    vendor_tax_number: str | None = None
    raw_values: dict[str, str] = field(default_factory=dict)
    field_confidence: dict[str, str] = field(default_factory=dict)


# Deliberately generic, not quotation/PO-specific wording. "supplier"/
# "vendor" bare labels are the lowest-priority (shortest, least specific)
# entries -- same accepted trade-off already used for quotation's own bare
# "reference" label (see `import_extraction._FIELD_LABELS`'s comment): a
# document that also has a more specific labeled line is matched by that
# one first, since `_VENDOR_FIELD_ORDER` below sorts longer labels first.
_VENDOR_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "vendor_name": (
        "subcontractor name",
        "supplier name",
        "vendor name",
        "subcontractor",
        "supplier",
        "vendor",
    ),
    "vendor_tax_number": (
        "vat registration number",
        "tax registration number",
        "vat registration no",
        "tax registration no",
        "vat number",
        "vat no",
        "trn",
    ),
}

_VENDOR_FIELD_ORDER = sorted(
    ((field_name, label) for field_name, labels in _VENDOR_FIELD_LABELS.items() for label in labels),
    key=lambda pair: -len(pair[1]),
)


def _apply_field(result: VendorCandidateFields, field_name: str, raw_value: str) -> None:
    result.raw_values[field_name] = raw_value
    setattr(result, field_name, raw_value)
    result.field_confidence[field_name] = ConfidenceLevel.HIGH.value


def extract_vendor_candidate(text: str | None, tables: list[ExtractedTable]) -> VendorCandidateFields:
    """Scan `text`/`tables` for a vendor's name and/or VAT/tax registration
    number, using the same first-match-wins, longer-label-first line
    scanning as `import_extraction.extract_quotation_candidate` and
    `po_extraction.extract_purchase_order_candidate`. Purely deterministic
    pattern matching -- no AI/ML model, no fuzzy matching. Returns a
    `VendorCandidateFields` with both fields `None` when nothing matches;
    callers (see `app.services.vendor_matching.match_vendor`) must treat
    that as "no vendor identity found on this document", never guess one.
    """
    result = VendorCandidateFields()
    lines = _candidate_lines(text, tables)
    found: set[str] = set()

    for field_name, label in _VENDOR_FIELD_ORDER:
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

    return result


__all__ = ["VendorCandidateFields", "extract_vendor_candidate"]
