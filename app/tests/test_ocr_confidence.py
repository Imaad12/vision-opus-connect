import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.enums import ConfidenceLevel, OcrConfidenceStatus
from app.core.ocr_confidence import compute_ocr_confidence_status


@dataclass
class _FakeCandidate:
    net_value: Decimal | None
    quotation_date: date | None
    field_confidence: str | None


@dataclass
class _FakeBoqLine:
    amount_flagged: bool = False


def _confidence_json(**fields: str) -> str:
    return json.dumps(fields)


def test_no_candidate_is_blocked() -> None:
    assert compute_ocr_confidence_status(None) == OcrConfidenceStatus.BLOCKED


def test_missing_net_value_is_blocked() -> None:
    candidate = _FakeCandidate(
        net_value=None,
        quotation_date=date(2018, 11, 21),
        field_confidence=_confidence_json(quotation_date=ConfidenceLevel.HIGH.value),
    )
    assert compute_ocr_confidence_status(candidate) == OcrConfidenceStatus.BLOCKED


def test_missing_quotation_date_is_blocked() -> None:
    candidate = _FakeCandidate(
        net_value=Decimal("168495.00"),
        quotation_date=None,
        field_confidence=_confidence_json(net_value=ConfidenceLevel.HIGH.value),
    )
    assert compute_ocr_confidence_status(candidate) == OcrConfidenceStatus.BLOCKED


def test_clean_extraction_is_high_confidence() -> None:
    candidate = _FakeCandidate(
        net_value=Decimal("168495.00"),
        quotation_date=date(2018, 11, 21),
        field_confidence=_confidence_json(
            net_value=ConfidenceLevel.HIGH.value,
            quotation_date=ConfidenceLevel.HIGH.value,
            quotation_number=ConfidenceLevel.HIGH.value,
        ),
    )
    assert compute_ocr_confidence_status(candidate) == OcrConfidenceStatus.HIGH_CONFIDENCE


def test_any_low_confidence_field_requires_review() -> None:
    candidate = _FakeCandidate(
        net_value=Decimal("168495.00"),
        quotation_date=date(2018, 11, 21),
        field_confidence=_confidence_json(
            net_value=ConfidenceLevel.HIGH.value,
            quotation_date=ConfidenceLevel.HIGH.value,
            quotation_number=ConfidenceLevel.LOW.value,
        ),
    )
    assert compute_ocr_confidence_status(candidate) == OcrConfidenceStatus.REVIEW_REQUIRED


def test_flagged_boq_line_requires_review_even_with_clean_quotation_fields() -> None:
    candidate = _FakeCandidate(
        net_value=Decimal("168495.00"),
        quotation_date=date(2018, 11, 21),
        field_confidence=_confidence_json(
            net_value=ConfidenceLevel.HIGH.value,
            quotation_date=ConfidenceLevel.HIGH.value,
        ),
    )
    boq_lines = [_FakeBoqLine(amount_flagged=False), _FakeBoqLine(amount_flagged=True)]
    assert compute_ocr_confidence_status(candidate, boq_lines) == OcrConfidenceStatus.REVIEW_REQUIRED


def test_no_field_confidence_at_all_requires_review_not_high_confidence() -> None:
    candidate = _FakeCandidate(
        net_value=Decimal("168495.00"),
        quotation_date=date(2018, 11, 21),
        field_confidence=None,
    )
    assert compute_ocr_confidence_status(candidate) == OcrConfidenceStatus.REVIEW_REQUIRED
