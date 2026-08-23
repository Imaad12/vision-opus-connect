"""Semantic labels for variance figures.

A positive number is not inherently "good" — a positive cost variance is a
cost overrun (unfavorable), while a positive profit variance is
outperformance (favorable). This module maps a variance's sign to the
correct semantic label and sentiment so the UI never relies on "green
means positive" as a substitute for actually knowing which direction is
favorable for that particular figure.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from app.ui.formatting import PLACEHOLDER


class Sentiment(Enum):
    FAVORABLE = "favorable"
    UNFAVORABLE = "unfavorable"
    NEUTRAL = "neutral"


def describe_cost_variance(variance: Decimal | None) -> tuple[str, Sentiment]:
    """Cost variance: higher cost than estimated is unfavorable."""
    if variance is None:
        return PLACEHOLDER, Sentiment.NEUTRAL
    if variance > 0:
        return "Over Estimate", Sentiment.UNFAVORABLE
    if variance < 0:
        return "Under Estimate", Sentiment.FAVORABLE
    return "On Estimate", Sentiment.NEUTRAL


def describe_profit_variance(variance: Decimal | None) -> tuple[str, Sentiment]:
    """Profit/margin variance: higher than the baseline is favorable."""
    if variance is None:
        return PLACEHOLDER, Sentiment.NEUTRAL
    if variance > 0:
        return "Above Target", Sentiment.FAVORABLE
    if variance < 0:
        return "Below Target", Sentiment.UNFAVORABLE
    return "On Target", Sentiment.NEUTRAL


# Margin variance follows the same "higher is favorable" rule as profit.
describe_margin_variance = describe_profit_variance


def describe_revenue_variance(variance: Decimal | None) -> tuple[str, Sentiment]:
    """Revenue variance (the net effect of approved contract variations):
    higher revenue than originally awarded is favorable."""
    if variance is None:
        return PLACEHOLDER, Sentiment.NEUTRAL
    if variance > 0:
        return "Above Original Contract", Sentiment.FAVORABLE
    if variance < 0:
        return "Below Original Contract", Sentiment.UNFAVORABLE
    return "At Original Contract", Sentiment.NEUTRAL


SENTIMENT_COLORS: dict[Sentiment, str] = {
    Sentiment.FAVORABLE: "#1E7B45",
    Sentiment.UNFAVORABLE: "#B3261E",
    Sentiment.NEUTRAL: "#5F6368",
}
