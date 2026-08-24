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

    # A mandatory field flagged LOW (as opposed to merely NEEDS_REVIEW, or
    # simply absent from this dict) is not "needs a second look" -- it is
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
    if confidences.get("net_value") == ConfidenceLevel.LOW.value:
        return OcrConfidenceStatus.BLOCKED

    if not confidences:
        return OcrConfidenceStatus.REVIEW_REQUIRED

    if any(value != ConfidenceLevel.HIGH.value for value in confidences.values()):
        return OcrConfidenceStatus.REVIEW_REQUIRED

    if boq_lines and any(getattr(line, "amount_flagged", False) for line in boq_lines):
        return OcrConfidenceStatus.REVIEW_REQUIRED

    return OcrConfidenceStatus.HIGH_CONFIDENCE
