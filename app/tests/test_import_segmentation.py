"""Sequential quotation boundary detection (`app.core.import_segmentation`).

These are direct, adversarial tests of `detect_segments` and
`slice_raw_extraction_to_pages` against constructed page-tagged OCR text
(the same `--- Page N ---` shape `app.core.ocr_extraction` produces),
covering the 16 required cases from the sequential-segmentation brief.
Service-layer integration (persistence, lock/confirm/reject, boundary
edits invalidating candidates) is covered separately in
`test_import_service_ocr.py`.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.enums import ConfidenceLevel
from app.core.import_segmentation import detect_segments, slice_raw_extraction_to_pages
from app.importers.base import RawExtraction


def _pages(*chunks: str) -> str:
    """Build page-tagged OCR text from `(page_text, ...)` in page order,
    numbering pages 1..N -- the common case. Use raw f-strings with
    explicit `--- Page N ---` markers directly for tests that need
    specific/non-contiguous page numbers or gaps."""
    return "\n\n".join(f"--- Page {i} ---\n{chunk}" for i, chunk in enumerate(chunks, start=1))


# --- 1. One quotation spanning 10+ pages ----------------------------------


def test_one_quotation_spanning_many_pages_is_a_single_segment() -> None:
    pages = ["Reference: VN/QU/412/18\nDate: 21/11/2018\n"] + [f"BOQ line {i}\nQty: {i}\n" for i in range(2, 12)]
    raw = RawExtraction(text=_pages(*pages))
    segments = detect_segments(raw)
    assert len(segments) == 1
    assert segments[0].start_page == 1
    assert segments[0].end_page == 11
    assert segments[0].quotation_number == "VN/QU/412/18"


# --- 2. Two adjacent quotations --------------------------------------------


def test_two_adjacent_quotations_split_into_two_segments() -> None:
    raw = RawExtraction(
        text=_pages(
            "Reference: 444 REV / 18\nDate: 23.12.2018\n",
            "Reference: VN/QU/412/18\nDate: 27/11/2018\nNet Amount: 151,955.00\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2
    assert (segments[0].start_page, segments[0].end_page) == (1, 1)
    assert (segments[1].start_page, segments[1].end_page) == (2, 2)
    assert segments[0].quotation_number == "444 REV / 18"
    assert segments[1].quotation_number == "VN/QU/412/18"
    assert segments[1].boundary_confidence == ConfidenceLevel.HIGH.value


# --- 3. Three quotations in one PDF ----------------------------------------


def test_three_quotations_in_one_document_produce_three_segments() -> None:
    raw = RawExtraction(
        text=_pages(
            "Reference: A-001\nDate: 01/01/2024\n",
            "Reference: A-002\nDate: 02/01/2024\n",
            "Reference: A-003\nDate: 03/01/2024\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 3
    assert [s.quotation_number for s in segments] == ["A-001", "A-002", "A-003"]
    assert [(s.start_page, s.end_page) for s in segments] == [(1, 1), (2, 2), (3, 3)]


# --- 4. Reference missing from A but present on B ---------------------------


def test_reference_missing_from_first_quotation_but_present_on_second_still_splits() -> None:
    raw = RawExtraction(
        text=_pages(
            "Date: 23.12.2018\nSome cover text with no reference label at all.\n",
            "Reference: VN/QU/412/18\nDate: 27/11/2018\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2
    assert segments[0].quotation_number is None
    assert segments[1].quotation_number == "VN/QU/412/18"
    # A genuinely new reference appearing is the strong signal -- HIGH,
    # even though the preceding segment never had one to compare against.
    assert segments[1].boundary_confidence == ConfidenceLevel.HIGH.value


# --- 5. Date missing from A but present on B (no reference change) ---------


def test_date_only_signal_with_no_reference_is_low_confidence() -> None:
    raw = RawExtraction(
        text=_pages(
            "Reference: VN/QU/412/18\nSome text, no date recognized here.\n",
            "Date: 27/11/2018\nNet Amount: 151,955.00\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2
    assert segments[1].boundary_confidence == ConfidenceLevel.LOW.value
    assert "no reference on this page" in segments[1].boundary_signals[0]


# --- 6. Both reference/date missing from A (B still has its own) -----------


def test_first_quotation_with_no_identity_at_all_still_lets_second_quotation_split() -> None:
    raw = RawExtraction(
        text=_pages(
            "Scope of works: general fit-out, no reference or date line at all.\n",
            "Reference: VN/QU/412/18\nDate: 27/11/2018\nNet Amount: 151,955.00\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2
    assert segments[0].quotation_number is None
    assert segments[0].quotation_date is None
    assert segments[1].quotation_number == "VN/QU/412/18"


# --- 7. Continuation BOQ pages with no header -------------------------------


def test_boq_continuation_pages_with_no_header_stay_in_the_open_segment() -> None:
    raw = RawExtraction(
        text=_pages(
            "Reference: VN/QU/412/18\nDate: 21/11/2018\n",
            "Item 1 Supply and install cables\nQty: 100\nRate: 50.00\n",
            "Item 2 Supply and install trunking\nQty: 40\nRate: 75.00\n",
            "Net Amount: 151,955.00\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 1
    assert (segments[0].start_page, segments[0].end_page) == (1, 4)


# --- 8. Attachment/drawing pages --------------------------------------------


def test_low_text_attachment_pages_do_not_start_a_new_segment() -> None:
    raw = RawExtraction(
        text=_pages(
            "Reference: VN/QU/412/18\nDate: 21/11/2018\n",
            "",  # a drawing/attachment page OCR found essentially nothing on
            "Net Amount: 151,955.00\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 1
    assert (segments[0].start_page, segments[0].end_page) == (1, 3)


# --- 9. Similar references ---------------------------------------------------


def test_similar_but_distinct_references_still_split() -> None:
    raw = RawExtraction(
        text=_pages(
            "Reference: VN/QU/412/18\nDate: 21/11/2018\n",
            "Reference: VN/QU/413/18\nDate: 22/11/2018\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2
    assert segments[0].quotation_number == "VN/QU/412/18"
    assert segments[1].quotation_number == "VN/QU/413/18"


# --- 10. OCR-garbled references (known, documented trade-off) --------------


def test_ocr_garbled_reference_variant_over_splits_rather_than_silently_merging() -> None:
    """A real, accepted trade-off: this application cannot tell the
    difference between "OCR corrupted one character of the same
    reference" and "a genuinely new, similar reference" from the string
    alone. It deliberately errs toward over-splitting (safe -- a reviewer
    just merges the two pieces back with `merge_segments`) rather than
    ever silently treating two different-looking strings as the same
    quotation (which could hide a real new document). Both this test and
    `test_similar_but_distinct_references_still_split` above prove the
    same conservative bias from different real angles."""
    raw = RawExtraction(
        text=_pages(
            "Reference: VN/QU/412/18\nDate: 21/11/2018\n",
            # A single OCR-plausible digit/letter corruption of the SAME
            # underlying reference ("4" -> "l").
            "Reference: VN/QU/4l2/18\nDate: 21/11/2018\nNet Amount: 168,495.00\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2, "over-splitting on a garbled variant is the safe, expected behavior"


# --- 11. Financial total on a later page ------------------------------------


def test_financial_total_several_pages_into_the_same_quotation_stays_attached() -> None:
    """The positive case this whole feature exists for: a real
    quotation's total legitimately appears several pages after its cover
    -- must stay part of the SAME segment, not be treated as ambiguous."""
    raw = RawExtraction(
        text=_pages(
            "Reference: VN/QU/412/18\nDate: 21/11/2018\n",
            "Item 1 description\nQty: 10\n",
            "Item 2 description\nQty: 5\n",
            "Item 3 description\nQty: 8\n",
            "Net Amount: 151,955.00\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 1
    sliced = slice_raw_extraction_to_pages(raw, segments[0].start_page, segments[0].end_page)
    from app.core.import_extraction import extract_quotation_candidate

    candidate = extract_quotation_candidate(sliced.text, sliced.tables)
    assert candidate.quotation_number == "VN/QU/412/18"
    assert candidate.net_value == Decimal("151955.00")


def test_financial_total_that_actually_belongs_to_the_next_quotation_is_excluded_by_slicing() -> None:
    """The original adversarial-review residual risk, now closed: a total
    physically printed after a new reference/date must never be readable
    from the *first* quotation's sliced extraction."""
    raw = RawExtraction(
        text=_pages(
            "Reference: 444 REV / 18\nDate: 23.12.2018\n",
            "Reference: VN/QU/412/18\nDate: 27/11/2018\nNet Amount: 151,955.00\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2
    first_slice = slice_raw_extraction_to_pages(raw, segments[0].start_page, segments[0].end_page)
    assert "151,955.00" not in (first_slice.text or "")

    from app.core.import_extraction import extract_quotation_candidate

    first_candidate = extract_quotation_candidate(first_slice.text, first_slice.tables)
    assert first_candidate.net_value is None
    assert first_candidate.quotation_number == "444 REV / 18"


# --- 12. Page slicing off-by-one at both boundaries -------------------------


def test_slicing_is_exact_at_both_boundaries_no_off_by_one() -> None:
    raw = RawExtraction(text=_pages("PAGE-ONE-TEXT", "PAGE-TWO-TEXT", "PAGE-THREE-TEXT", "PAGE-FOUR-TEXT"))

    only_page_2 = slice_raw_extraction_to_pages(raw, 2, 2)
    assert "PAGE-TWO-TEXT" in only_page_2.text
    assert "PAGE-ONE-TEXT" not in only_page_2.text
    assert "PAGE-THREE-TEXT" not in only_page_2.text

    pages_2_to_3 = slice_raw_extraction_to_pages(raw, 2, 3)
    assert "PAGE-TWO-TEXT" in pages_2_to_3.text
    assert "PAGE-THREE-TEXT" in pages_2_to_3.text
    assert "PAGE-ONE-TEXT" not in pages_2_to_3.text
    assert "PAGE-FOUR-TEXT" not in pages_2_to_3.text

    whole_document = slice_raw_extraction_to_pages(raw, 1, 4)
    for chunk in ("PAGE-ONE-TEXT", "PAGE-TWO-TEXT", "PAGE-THREE-TEXT", "PAGE-FOUR-TEXT"):
        assert chunk in whole_document.text

    # A range that includes a page number with no corresponding marker at
    # all (e.g. after a boundary edit against a stale range) must not
    # crash -- it just yields whatever pages actually exist in range.
    partially_out_of_range = slice_raw_extraction_to_pages(raw, 4, 6)
    assert "PAGE-FOUR-TEXT" in partially_out_of_range.text


def test_slicing_scopes_ocr_pages_metadata_to_the_requested_range() -> None:
    raw = RawExtraction(
        text=_pages("A", "B", "C"),
        ocr_pages=[
            {"page_number": 1, "char_count": 1, "mean_confidence": 90.0, "failed": False},
            {"page_number": 2, "char_count": 1, "mean_confidence": 91.0, "failed": False},
            {"page_number": 3, "char_count": 1, "mean_confidence": 92.0, "failed": False},
        ],
    )
    sliced = slice_raw_extraction_to_pages(raw, 2, 3)
    assert [p["page_number"] for p in sliced.ocr_pages] == [2, 3]


# --- Additional structural cases -------------------------------------------


def test_no_page_markers_returns_no_segments() -> None:
    """No page structure at all -- segmentation has nothing to work with;
    the caller (`app.services.import_service.propose_segments`) falls
    back to the original single-candidate behavior for this case."""
    raw = RawExtraction(text="Reference: VN/QU/412/18\nDate: 21/11/2018\nNet Amount: 151,955.00\n")
    assert detect_segments(raw) == []


def test_no_identity_signal_anywhere_yields_one_low_confidence_segment() -> None:
    raw = RawExtraction(text=_pages("Just some cover text.", "And some more scope text.", "No labeled fields at all."))
    segments = detect_segments(raw)
    assert len(segments) == 1
    assert segments[0].start_page == 1
    assert segments[0].end_page == 3
    assert segments[0].boundary_confidence == ConfidenceLevel.LOW.value
    assert "could not establish any boundary" in segments[0].boundary_signals[0]


def test_leading_text_before_first_page_marker_is_preserved_not_dropped() -> None:
    """Defensive case: content appearing before the first `--- Page N ---`
    marker (never produced by the real OCR pipeline, which always tags
    page 1, but a defensive case worth covering directly) must never be
    silently discarded -- it is treated as page 1."""
    raw = RawExtraction(text="Reference: 444 REV / 18\nDate: 23.12.2018\n--- Page 8 ---\nReference: VN/QU/412/18\n")
    segments = detect_segments(raw)
    assert len(segments) == 2
    assert segments[0].start_page == 1
    assert segments[0].quotation_number == "444 REV / 18"
    assert segments[1].start_page == 8


def test_contradictory_same_reference_different_date_is_low_confidence() -> None:
    raw = RawExtraction(
        text=_pages(
            "Reference: VN/QU/412/18\nDate: 21/11/2018\n",
            "Reference: VN/QU/412/18\nDate: 25/12/2019\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2
    assert segments[1].boundary_confidence == ConfidenceLevel.LOW.value
    assert "signals disagree" in segments[1].boundary_signals[0]


def test_same_date_different_reference_still_splits_high_confidence() -> None:
    raw = RawExtraction(
        text=_pages(
            "Reference: A-100\nDate: 01/01/2024\n",
            "Reference: A-200\nDate: 01/01/2024\n",
        )
    )
    segments = detect_segments(raw)
    assert len(segments) == 2
    assert segments[1].boundary_confidence == ConfidenceLevel.HIGH.value
