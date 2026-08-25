"""Minimum-viable confidence gate for OCR-derived import candidates (OCR
Phase 1). See `app.core.enums.OcrConfidenceStatus` for what each state
means and why there are only three.

Deliberately not a scoring framework: this is one small pure function
over the *current* state of a staged candidate (so it always reflects the
reviewer's latest edits), reusing the existing per-field `ConfidenceLevel`
values `app.core.import_extraction` already computes rather than
introducing a second confidence vocabulary. It has no knowledge of OCR,
Tesseract, or pixels — it only looks at what ended up in the candidate.
"""

from __future__ import annotations

import json

from app.core.enums import ConfidenceLevel, OcrConfidenceStatus

# The two fields a confirmed QuotationVersion is actually built from
# (`quoted_value`, `issued_date`) -- see app.services.quotation_service.
# Everything else on the candidate is useful but not load-bearing for the
# financial record itself, and PR #5's revision-conflict protection
# already depends on both of these being present to do its job.
_MANDATORY_FIELDS = ("net_value", "quotation_date")


def compute_ocr_confidence_status(
    candidate,
    boq_lines: list | None = None,
) -> OcrConfidenceStatus:
    """`candidate` is an `ImportedQuotationCandidate` (or `None`).
    `boq_lines` is the document's `ImportedBoqLineCandidate` list, if any.
    """
    if candidate is None:
        return OcrConfidenceStatus.BLOCKED

    if getattr(candidate, "net_value", None) is None or getattr(candidate, "quotation_date", None) is None:
        return OcrConfidenceStatus.BLOCKED

    raw_confidence = getattr(candidate, "field_confidence", None)
    try:
        confidences: dict = json.loads(raw_confidence) if raw_confidence else {}
    except (TypeError, ValueError):
        confidences = {}

    # A mandatory field flagged LOW is not "needs a second look" -- it is
    # exactly as untrustworthy as that field being missing outright. The
    # one producer of this specific state today is
    # `app.services.import_service._flag_financial_fields_without_
    # identity_corroboration`: a net_value found on a page that shares no
    # page with the reference or date it would be confirmed alongside
    # (adversarial-review finding -- see IMPORT_ARCHITECTURE.md). Treating
    # it as BLOCKED, not just REVIEW_REQUIRED, is what makes this a
    # structural gate rather than a cosmetic confidence label: it disables
    # Confirm in the UI *and* is enforced defensively inside
    # `confirm_import` itself, the same way a missing value already is.
    #
    # NEEDS_REVIEW is treated exactly the same way (OCR Phase 4 real-
    # archive fix). Its one producer is `reconcile_net_tax_gross`
    # deriving net_value algebraically from tax + gross rather than
    # reading it directly -- meaning it was never independently found on
    # any single page at all, so the identity-corroboration check above
    # can never run against it (nothing to compare pages to). Reproduced
    # directly against the real archive: an incorrectly-merged segment
    # (two different documents' pages bundled together, still a real,
    # open extraction-boundary limitation) derived a net_value this way
    # from one document's tax figure and a different, unrelated
    # document's gross figure -- a genuinely wrong number that a fixed
    # date-parsing bug had incidentally been leaving BLOCKED for the
    # wrong reason. A derived-not-read net_value must never be
    # confirmable without a human explicitly re-entering or verifying it,
    # regardless of why it wasn't independently found.
    if confidences.get("net_value") in (ConfidenceLevel.LOW.value, ConfidenceLevel.NEEDS_REVIEW.value):
        return OcrConfidenceStatus.BLOCKED

    if not confidences:
        return OcrConfidenceStatus.REVIEW_REQUIRED

    if any(value != ConfidenceLevel.HIGH.value for value in confidences.values()):
        return OcrConfidenceStatus.REVIEW_REQUIRED

    if boq_lines and any(getattr(line, "amount_flagged", False) for line in boq_lines):
        return OcrConfidenceStatus.REVIEW_REQUIRED

    return OcrConfidenceStatus.HIGH_CONFIDENCE
