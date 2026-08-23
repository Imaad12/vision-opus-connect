"""Labels/colors for extraction confidence and BOQ amount-mismatch flags.

Kept separate from `app.ui.variance_labels` deliberately: extraction
confidence ("did the parser recognize this cleanly?") and financial
variance sentiment ("is this number good or bad for the business?") are
different concepts that happen to reuse the same `Badge` widget — folding
them into one mapping would blur that distinction.
"""

from __future__ import annotations

from app.core.enums import ConfidenceLevel
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
