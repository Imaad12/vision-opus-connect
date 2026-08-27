"""Vendor identity -> `Vendor` master-record matching (Supplier/Vendor
intelligence foundation).

Mirrors `app.services.po_matching`'s own discipline deliberately: exact,
whitespace-and-case-normalized string comparison only, never fuzzy or
similarity-based. A standalone module (not imported by, and not
importing, `import_service.py`'s staging functions directly at module
scope where it would risk a cycle) so it can be called both at extraction
time (a preview, computed immediately) and reused by any future
reconciliation step, the same way `po_matching.match_quotation_for_reference`
is reused by both `import_service.run_po_extraction` and
`purchase_order_service.reconcile_unmatched_purchase_orders`.

Matching hierarchy, strongest signal first, never combined: a VAT/tax
registration number is the more authoritative identifier (two vendors
should never legitimately share one), so it is tried first; a name is
tried only if no tax number was extracted, or if the extracted tax number
matched no vendor on file yet (e.g. an existing vendor record that
predates tax-number tracking). Whichever signal is tried, an exact
match against more than one vendor is `AMBIGUOUS` immediately -- this
never falls through to try a weaker signal to "break the tie" (that would
be exactly the kind of guessing this project's PO/quotation matching has
always refused to do), and it never checks a weaker signal once a
signal has produced a match at all (checking a second signal afterwards
could only ever contradict the first, never usefully confirm it, since
both are already treated as individually authoritative when they hit
exactly one record).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PurchaseOrderMatchStatus
from app.core.import_normalization import normalize_whitespace
from app.models import Vendor

__all__ = ["VendorMatchOutcome", "match_vendor"]


@dataclass(frozen=True, slots=True)
class VendorMatchOutcome:
    """Result of resolving an extracted vendor name/tax number against
    existing `Vendor` records -- see `match_vendor`.

    Reuses `PurchaseOrderMatchStatus` for its `status` values (`MATCHED`/
    `UNMATCHED`/`AMBIGUOUS`) rather than introducing a near-duplicate
    enum: those three outcomes already mean exactly the same thing here
    as they do for PO-to-quotation matching, and the enum's own value
    strings carry no PO-specific meaning -- only its class name does.
    """

    status: PurchaseOrderMatchStatus
    vendor: Vendor | None = None
    matched_on: str | None = None  # "tax_number" | "name" | None
    candidate_vendor_ids: list[int] = field(default_factory=list)


def _normalized_identity(value: str | None) -> str | None:
    normalized = normalize_whitespace(value)
    return normalized.casefold() if normalized else None


def match_vendor(
    session: Session,
    *,
    vendor_name: str | None = None,
    vendor_tax_number: str | None = None,
) -> VendorMatchOutcome:
    """Resolve an extracted vendor name and/or tax number to an existing
    `Vendor`, trying `vendor_tax_number` first, then `vendor_name` — see
    module docstring for the exact hierarchy and why neither signal is
    ever combined with or corroborated by the other.

    Returns `UNMATCHED` if neither signal is provided, or if every
    provided signal matches zero vendors. Never guesses between
    candidates, and never treats a bare substring/similarity as a match.
    """
    signals = [
        ("tax_number", vendor_tax_number, Vendor.tax_number),
        ("name", vendor_name, Vendor.name),
    ]

    vendors: list[Vendor] | None = None
    for signal_name, raw_value, column in signals:
        normalized = _normalized_identity(raw_value)
        if not normalized:
            continue
        if vendors is None:
            vendors = list(
                session.execute(select(Vendor).where(Vendor.is_deleted.is_(False))).scalars().all()
            )
        matches = [v for v in vendors if _normalized_identity(getattr(v, column.key)) == normalized]
        if not matches:
            continue
        if len(matches) > 1:
            return VendorMatchOutcome(
                status=PurchaseOrderMatchStatus.AMBIGUOUS,
                matched_on=signal_name,
                candidate_vendor_ids=[v.id for v in matches],
            )
        return VendorMatchOutcome(status=PurchaseOrderMatchStatus.MATCHED, vendor=matches[0], matched_on=signal_name)

    return VendorMatchOutcome(status=PurchaseOrderMatchStatus.UNMATCHED)
