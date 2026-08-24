"""Sequential quotation boundary detection (OCR sequential segmentation).

A scanned batch upload is one PDF containing several consecutive quotation
documents, in document order (see IMPORT_ARCHITECTURE.md's sequential
segmentation section for the full design this implements). This module
turns one OCR'd document's page-tagged `RawExtraction` into an ordered
list of proposed page-range segments — never more than that. It never
writes to the database, never decides a boundary is final (only a human
reviewer does, via `app.services.import_service`'s segment functions),
and never runs any AI/ML model — composite pattern matching over the
*same* label-based field extraction `app.core.import_extraction` already
uses, applied one page at a time.

Core safety invariant this module exists to serve, enforced structurally
by `slice_raw_extraction_to_pages` rather than by any downstream check: a
quotation candidate built from a sliced `RawExtraction` can never see a
page outside its own accepted range, because that page's text/tables are
never included in the sliced object handed to `extract_candidates` in the
first place.

Deliberately conservative, per the approved design: a fixed page-distance
threshold between identity and financial signals is never used (a
legitimate quotation may span many pages); the only signals trusted to
start a *new* segment are a reference or date that genuinely differs from
the currently open segment's own identity. Everything else — a missing
header, a blank/low-text page, a repeated reference/date, a page with no
signal at all — defaults to *continuing* the open segment. A missed
header can therefore only ever under-split (a segment too long, which a
reviewer splits) or over-split (a late-revealed new reference the
reviewer merges back) — never mis-attribute a page to the wrong
quotation without a human being shown the seam first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.core.enums import ConfidenceLevel
from app.core.import_extraction import QuotationCandidateFields, extract_quotation_candidate
from app.importers.base import ExtractedTable, RawExtraction

_PAGE_MARKER_RE = re.compile(r"--- Page (\d+) ---\n")
_TABLE_PAGE_RE = re.compile(r"^page (\d+)\b", re.IGNORECASE)


@dataclass
class PageSegment:
    """One proposed quotation-page range, before any reviewer has looked
    at it. `start_page`/`end_page` are 1-based and inclusive, matching the
    `--- Page N ---` markers `app.core.ocr_extraction` already emits.

    `boundary_confidence` describes the signal that *opened* this segment
    (i.e. the boundary between the previous segment and this one) — the
    first segment in a document has no incoming boundary to describe, so
    it is always reported HIGH (it is exactly where the document starts,
    not a detected transition). `quotation_number`/`quotation_date` are
    the identity this segment's own pages established during detection —
    a display convenience for the reviewer, not a substitute for running
    real extraction later.
    """

    start_page: int
    end_page: int
    boundary_confidence: str
    boundary_signals: list[str] = field(default_factory=list)
    quotation_number: str | None = None
    quotation_date: date | None = None


def _split_pages(text: str | None) -> dict[int, str]:
    """Split OCR text on `--- Page N ---` markers into `{page_number:
    page_text}`. Returns an empty dict for text with no page markers at
    all (the deterministic, non-OCR import path — segmentation never runs
    for those; see `app.services.import_service`).

    Any content appearing *before* the first marker is preserved, never
    silently dropped, by treating it as page 1 -- the real OCR pipeline
    (`app.core.ocr_extraction`) always tags its first page, so this path
    is not expected to trigger there; it exists purely as a defensive
    fallback so a malformed/synthetic input can never lose real content.
    """
    if not text:
        return {}
    matches = list(_PAGE_MARKER_RE.finditer(text))
    if not matches:
        return {}
    pages: dict[int, str] = {}
    leading = text[: matches[0].start()]
    if leading.strip():
        pages[1] = leading.rstrip("\n")
    for index, match in enumerate(matches):
        page_number = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages[page_number] = text[start:end].rstrip("\n")
    return pages


def _page_number_from_table_name(name: str | None) -> int | None:
    """`app.core.ocr_table_reconstruction.reconstruct_table_from_words`
    names every OCR-derived table `"page {N} (OCR)"` — the one place page
    identity survives for tables. Returns `None` for anything else
    (a deterministic import's sheet/section name), which callers treat as
    "this table has no known page"."""
    if not name:
        return None
    match = _TABLE_PAGE_RE.match(name.strip())
    return int(match.group(1)) if match else None


def find_field_pages(raw: RawExtraction, field_names: tuple[str, ...]) -> dict[str, int]:
    """For each name in `field_names`, the page number where that field
    was found -- specifically, the lowest-numbered page whose *own*,
    independent `extract_quotation_candidate` call finds a value for it.

    This deliberately matches `extract_quotation_candidate`'s own
    first-match-wins rule when it is instead run once on the whole
    (multi-page) slice: the first page in ascending order that contains
    any matching line for a field is exactly the page whose line a
    whole-slice extraction would have used, since a whole-slice scan
    encounters that page's lines before any later page's. No behavior of
    `extract_quotation_candidate` itself is changed or reimplemented here
    — this only re-runs it once per page (already exactly what
    `detect_segments` does for boundary detection) and records where the
    winning value came from.

    Returns only entries for fields actually found somewhere. Returns an
    empty dict for text with no page markers (nothing to attribute a page
    to)."""
    pages = _split_pages(raw.text)
    if not pages:
        return {}
    found: dict[str, int] = {}
    remaining = set(field_names)
    for page_number in sorted(pages):
        if not remaining:
            break
        page_tables = [t for t in raw.tables if _page_number_from_table_name(t.name) == page_number]
        fields = extract_quotation_candidate(pages[page_number], page_tables)
        for name in list(remaining):
            if getattr(fields, name, None) is not None:
                found[name] = page_number
                remaining.discard(name)
    return found


def slice_raw_extraction_to_pages(raw: RawExtraction, start_page: int, end_page: int) -> RawExtraction:
    """Build a new `RawExtraction` containing only the pages in
    `[start_page, end_page]` (inclusive). This is the structural
    enforcement of the core safety invariant: the returned object simply
    does not contain any other page's text or tables, so whatever calls
    `extract_candidates` on it cannot see — and therefore cannot extract
    a field from — a page outside the requested range. There is no
    downstream filtering step this depends on; the exclusion happens here,
    once, before extraction ever runs.
    """
    pages = _split_pages(raw.text)
    parts: list[str] = []
    for page_number in range(start_page, end_page + 1):
        page_text = pages.get(page_number)
        if page_text is not None:
            parts.append(f"--- Page {page_number} ---\n{page_text}")
    sliced_text = "\n\n".join(parts) if parts else None

    all_page_numbers = sorted(pages) if pages else []
    whole_document_range = bool(all_page_numbers) and (start_page, end_page) == (
        all_page_numbers[0],
        all_page_numbers[-1],
    )

    tables: list[ExtractedTable] = []
    for table in raw.tables:
        table_page = _page_number_from_table_name(table.name)
        if table_page is None:
            # An untagged table (no page identity at all -- the
            # deterministic-import shape) is only ever included when this
            # slice covers the *entire* document (no page markers at all,
            # or a slice spanning every known page): a partial OCR slice
            # must never guess which segment an untagged table belongs to.
            if not all_page_numbers or whole_document_range:
                tables.append(table)
            continue
        if start_page <= table_page <= end_page:
            tables.append(table)

    sliced_ocr_pages = None
    if raw.ocr_pages:
        sliced_ocr_pages = [
            page_info
            for page_info in raw.ocr_pages
            if start_page <= page_info.get("page_number", -1) <= end_page
        ]

    return RawExtraction(
        text=sliced_text,
        tables=tables,
        warnings=list(raw.warnings),
        requires_ocr=raw.requires_ocr,
        unsupported=raw.unsupported,
        unsupported_reason=raw.unsupported_reason,
        ocr_pages=sliced_ocr_pages,
    )


def _classify_boundary(
    page_reference: str | None,
    page_date: date | None,
    seg_reference: str | None,
    seg_date: date | None,
) -> tuple[str | None, str | None]:
    """Decide whether the field values found on one page represent a new
    segment boundary against the currently open segment's own identity.
    Returns `(signal_text, confidence)`, or `(None, None)` meaning "no
    boundary here -- this page continues the open segment."

    Reference is treated as the stronger signal (matching the ordering
    `app.core.import_extraction._FIELD_ORDER` already gives it, and the
    real-archive finding that reference labels are more reliable than
    date labels in this document set): a genuinely new reference alone is
    enough for a HIGH-confidence boundary, and a reference that matches
    the open segment's own is treated as confirming continuation even if
    the date on that page is new information (not yet known for this
    segment) -- there is nothing to disagree with yet.

    A date that changes (or first appears) with no reference on the same
    page to corroborate it either way is genuinely ambiguous: it could be
    this segment's own date, shown for the first time on a later page, or
    it could belong to an entirely different document whose reference was
    lost to OCR (the original adversarial-review finding this whole
    module exists to close). Per the "uncertain boundary -> manual
    review, never a silent guess" rule, this is never silently absorbed
    either way -- it is always surfaced, at LOW confidence, so a reviewer
    decides. The same applies when the open segment's reference is
    confirmed but its *already-known* date conflicts outright -- also
    LOW, never silently resolved.
    """
    reference_changed = page_reference is not None and page_reference != seg_reference
    reference_confirmed = page_reference is not None and page_reference == seg_reference
    date_conflicts = page_date is not None and seg_date is not None and page_date != seg_date
    date_first_seen = page_date is not None and seg_date is None
    date_is_new_information = date_conflicts or date_first_seen

    if reference_changed and date_is_new_information:
        return (
            f"New quotation reference ('{page_reference}', previous segment: '{seg_reference}') "
            f"and a new date ('{page_date.isoformat()}', previous segment: "
            f"'{seg_date.isoformat() if seg_date else 'unknown'}') both found on this page.",
            ConfidenceLevel.HIGH.value,
        )
    if reference_changed:
        return (
            f"New quotation reference on this page: '{page_reference}' "
            f"(previous segment: '{seg_reference}').",
            ConfidenceLevel.HIGH.value,
        )
    if reference_confirmed:
        # This page's own reference clearly matches the open segment's --
        # a same-page date is only worth flagging when it actually
        # conflicts with an already-known date; a first-seen date here is
        # unambiguous (the reference already proves continuation).
        if date_conflicts:
            return (
                f"This page repeats reference '{seg_reference}' but shows a different date "
                f"('{page_date.isoformat()}' vs '{seg_date.isoformat()}') -- signals disagree.",
                ConfidenceLevel.LOW.value,
            )
        return None, None
    if date_is_new_information:
        # No reference at all on this page -- nothing corroborates
        # whether this date belongs to the open segment or a different,
        # unidentified document.
        return (
            f"New quotation date on this page: '{page_date.isoformat()}' "
            f"(previous segment: '{seg_date.isoformat() if seg_date else 'unknown'}'), with no "
            "reference on this page to corroborate it.",
            ConfidenceLevel.LOW.value,
        )
    return None, None


def detect_segments(raw: RawExtraction) -> list[PageSegment]:
    """Propose an ordered list of page-range segments for one OCR'd
    document. Never final, never persisted here, never itself creates a
    candidate — see module docstring. Returns an empty list if `raw` has
    no page-tagged text at all (nothing to segment).
    """
    pages = _split_pages(raw.text)
    if not pages:
        return []
    page_numbers = sorted(pages)

    page_fields: dict[int, QuotationCandidateFields] = {}
    for page_number in page_numbers:
        page_tables = [t for t in raw.tables if _page_number_from_table_name(t.name) == page_number]
        page_fields[page_number] = extract_quotation_candidate(pages[page_number], page_tables)

    any_identity_signal = any(
        page_fields[p].quotation_number or page_fields[p].quotation_date for p in page_numbers
    )
    if not any_identity_signal:
        # No page anywhere in the document carries a recognizable
        # reference or date -- there is no basis to propose *any*
        # boundary. Per the approved design: do not guess where a split
        # might be. The whole document becomes one LOW-confidence segment
        # that a human must manually split before any extraction runs.
        return [
            PageSegment(
                start_page=page_numbers[0],
                end_page=page_numbers[-1],
                boundary_confidence=ConfidenceLevel.LOW.value,
                boundary_signals=[
                    "No quotation reference or date was recognized on any page of this "
                    "document -- segmentation could not establish any boundary. Split this "
                    "document into its individual quotations manually before it can be "
                    "extracted."
                ],
            )
        ]

    segments: list[PageSegment] = []
    seg_start = page_numbers[0]
    seg_reference = page_fields[seg_start].quotation_number
    seg_date = page_fields[seg_start].quotation_date
    seg_confidence = ConfidenceLevel.HIGH.value
    seg_signals = ["First page of the document."]

    for page_number in page_numbers[1:]:
        fields = page_fields[page_number]
        page_reference = fields.quotation_number
        page_date = fields.quotation_date

        signal, confidence = _classify_boundary(page_reference, page_date, seg_reference, seg_date)

        if signal is None:
            # Continuation: a first-seen reference/date for the still-open
            # segment (e.g. only shown on its second page) is absorbed
            # into that segment's own identity, not treated as a change.
            if page_reference is not None and seg_reference is None:
                seg_reference = page_reference
            if page_date is not None and seg_date is None:
                seg_date = page_date
            continue

        segments.append(
            PageSegment(
                start_page=seg_start,
                end_page=page_number - 1,
                boundary_confidence=seg_confidence,
                boundary_signals=seg_signals,
                quotation_number=seg_reference,
                quotation_date=seg_date,
            )
        )
        seg_start = page_number
        seg_reference = page_reference
        seg_date = page_date
        seg_confidence = confidence
        seg_signals = [signal]

    segments.append(
        PageSegment(
            start_page=seg_start,
            end_page=page_numbers[-1],
            boundary_confidence=seg_confidence,
            boundary_signals=seg_signals,
            quotation_number=seg_reference,
            quotation_date=seg_date,
        )
    )
    return segments


__all__ = ["PageSegment", "detect_segments", "find_field_pages", "slice_raw_extraction_to_pages"]
