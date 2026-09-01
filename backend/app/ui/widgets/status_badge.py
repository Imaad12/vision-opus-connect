"""A small, labeled status/sentiment chip.

Never relies on color alone: the text label always states the status or
sentiment in words (e.g. "Over Estimate"), with color as a secondary,
non-essential cue — satisfying the "don't rely on color alone" requirement
for anyone who can't distinguish the colors.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from app.ui.style import FAVORABLE, INK_MUTED, UNFAVORABLE
from app.ui.variance_labels import Sentiment

_SENTIMENT_COLOR = {
    Sentiment.FAVORABLE: FAVORABLE,
    Sentiment.UNFAVORABLE: UNFAVORABLE,
    Sentiment.NEUTRAL: INK_MUTED,
}


class Badge(QLabel):
    def __init__(self, text: str, color: str = INK_MUTED) -> None:
        super().__init__(text)
        self._apply_color(color)

    def _apply_color(self, color: str) -> None:
        # A flat property list (no type-selector block) applies directly to
        # this widget instance and avoids a spurious "could not parse
        # stylesheet" warning Qt emits for some per-widget QLabel{...} block
        # selectors once a global application stylesheet is also active.
        self.setStyleSheet(
            f"color: {color}; border: 1px solid {color}; border-radius: 4px; "
            "padding: 2px 8px; font-size: 11px; font-weight: 600;"
        )

    def set_sentiment(self, text: str, sentiment: Sentiment) -> None:
        self.setText(text)
        self._apply_color(_SENTIMENT_COLOR[sentiment])


def sentiment_badge(text: str, sentiment: Sentiment) -> Badge:
    return Badge(text, _SENTIMENT_COLOR[sentiment])
