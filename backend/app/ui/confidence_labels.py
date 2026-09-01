"""Labels/colors for extraction confidence and BOQ amount-mismatch flags.

Kept separate from `app.ui.variance_labels` deliberately: extraction
confidence ("did the parser recognize this cleanly?") and financial
variance sentiment ("is this number good or bad for the business?") are
different concepts that happen to reuse the same `Badge` widget — folding
them into one mapping would blur that distinction.
"""

from __future__ import annotations

from app.core.enums import ConfidenceLevel, OcrConfidenceStatus
from app.ui.style import FAVORABLE, INK_MUTED, UNFAVORABLE

CONFIDENCE_LABELS = {
    ConfidenceLevel.HIGH: "High confidence",
    ConfidenceLevel.NEEDS_REVIEW: "Needs review",
    ConfidenceLevel.LOW: "Low confidence",
}

CONFIDENCE_COLORS = {
    ConfidenceLevel.HIGH: FAVORABLE,
    ConfidenceLevel.NEEDS_REVIEW: INK_MUTED,
    ConfidenceLevel.LOW: UNFAVORABLE,
}

AMOUNT_OK_LABEL = "Amount matches"
AMOUNT_FLAGGED_LABEL = "Check amount"

# OCR Phase 1's minimum-viable document-level gate -- see
# `app.core.enums.OcrConfidenceStatus` for what each state means.
OCR_STATUS_LABELS = {
    OcrConfidenceStatus.HIGH_CONFIDENCE: "OCR: high confidence",
    OcrConfidenceStatus.REVIEW_REQUIRED: "OCR: review required",
    OcrConfidenceStatus.BLOCKED: "OCR: cannot confirm yet",
}

OCR_STATUS_COLORS = {
    OcrConfidenceStatus.HIGH_CONFIDENCE: FAVORABLE,
    OcrConfidenceStatus.REVIEW_REQUIRED: INK_MUTED,
    OcrConfidenceStatus.BLOCKED: UNFAVORABLE,
}
