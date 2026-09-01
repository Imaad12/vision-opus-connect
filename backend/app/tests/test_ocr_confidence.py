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


def test_needs_review_net_value_is_blocked_not_merely_review_required() -> None:
    """OCR Phase 4 real-archive fix: a `net_value` that was algebraically
    derived (`reconcile_net_tax_gross`, from tax + gross) rather than
    directly read is flagged NEEDS_REVIEW, not LOW -- but it was never
    independently found on any page, so the identity-corroboration check
    can never run against it. Reproduced against the real archive: a
    still-incorrectly-merged segment derived a net_value from one
    document's tax figure and a different document's gross figure, and a
    date-parsing fix elsewhere had incidentally been the only thing
    keeping this BLOCKED. A derived value must always require explicit
    human confirmation, the same as a LOW-flagged one."""
    candidate = _FakeCandidate(
        net_value=Decimal("744.77"),
        quotation_date=date(2018, 11, 19),
        field_confidence=_confidence_json(
            net_value=ConfidenceLevel.NEEDS_REVIEW.value,
            tax_value=ConfidenceLevel.HIGH.value,
            gross_value=ConfidenceLevel.HIGH.value,
        ),
    )
    assert compute_ocr_confidence_status(candidate) == OcrConfidenceStatus.BLOCKED
