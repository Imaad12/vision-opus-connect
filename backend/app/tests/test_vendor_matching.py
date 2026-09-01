"""Tests for `app.services.vendor_matching.match_vendor` -- deterministic,
never-fuzzy vendor identity resolution. Mirrors `test_po_matching.py`'s
own discipline (if that file doesn't exist yet, this establishes the same
one for the vendor side): exact match, unmatched, ambiguous, and
normalization that is whitespace/case-only, never similarity-based."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.enums import ClientAwardEvidenceMatchStatus, VendorType
from app.models import Vendor
from app.services.vendor_matching import match_vendor


def _make_vendor(session: Session, *, name: str, tax_number: str | None = None) -> Vendor:
    vendor = Vendor(vendor_type=VendorType.SUPPLIER, name=name, tax_number=tax_number)
    session.add(vendor)
    session.flush()
    return vendor


def test_exact_tax_number_match(db_session: Session) -> None:
    vendor = _make_vendor(db_session, name="Gulf Steel Trading LLC", tax_number="100234567800003")

    outcome = match_vendor(db_session, vendor_tax_number="100234567800003")

    assert outcome.status == ClientAwardEvidenceMatchStatus.MATCHED
    assert outcome.vendor is not None
    assert outcome.vendor.id == vendor.id
    assert outcome.matched_on == "tax_number"


def test_exact_name_match_when_no_tax_number_given(db_session: Session) -> None:
    vendor = _make_vendor(db_session, name="Al Rashid Building Materials")

    outcome = match_vendor(db_session, vendor_name="Al Rashid Building Materials")

    assert outcome.status == ClientAwardEvidenceMatchStatus.MATCHED
    assert outcome.vendor.id == vendor.id
    assert outcome.matched_on == "name"


def test_name_match_is_whitespace_and_case_normalized_not_fuzzy(db_session: Session) -> None:
    vendor = _make_vendor(db_session, name="Gulf   Steel Trading LLC")

    outcome = match_vendor(db_session, vendor_name="gulf steel trading llc")

    assert outcome.status == ClientAwardEvidenceMatchStatus.MATCHED
    assert outcome.vendor.id == vendor.id


def test_similar_but_not_identical_name_is_unmatched_not_guessed(db_session: Session) -> None:
    """The safety requirement this whole module exists for: no fuzzy
    matching, ever. A name that a human would recognize as "probably the
    same vendor" but that isn't identical after normalization must stay
    UNMATCHED, not be silently accepted."""
    _make_vendor(db_session, name="Gulf Steel Trading LLC")

    outcome = match_vendor(db_session, vendor_name="Gulf Steel Trading Company")

    assert outcome.status == ClientAwardEvidenceMatchStatus.UNMATCHED
    assert outcome.vendor is None


def test_no_signals_at_all_is_unmatched(db_session: Session) -> None:
    _make_vendor(db_session, name="Some Vendor")

    outcome = match_vendor(db_session)

    assert outcome.status == ClientAwardEvidenceMatchStatus.UNMATCHED


def test_tax_number_matching_two_vendors_is_ambiguous(db_session: Session) -> None:
    # Not expected in well-formed real data (tax numbers should be
    # unique), but the matcher must never guess between them if it
    # happens -- e.g. a duplicate master-record entry.
    v1 = _make_vendor(db_session, name="Vendor One", tax_number="100000000000001")
    v2 = _make_vendor(db_session, name="Vendor Two", tax_number="100000000000001")

    outcome = match_vendor(db_session, vendor_tax_number="100000000000001")

    assert outcome.status == ClientAwardEvidenceMatchStatus.AMBIGUOUS
    assert outcome.vendor is None
    assert set(outcome.candidate_vendor_ids) == {v1.id, v2.id}


def test_name_matching_two_vendors_is_ambiguous(db_session: Session) -> None:
    v1 = _make_vendor(db_session, name="Shared Name Trading")
    v2 = Vendor(vendor_type=VendorType.SUBCONTRACTOR, name="Shared Name Trading")
    db_session.add(v2)
    db_session.flush()

    outcome = match_vendor(db_session, vendor_name="Shared Name Trading")

    assert outcome.status == ClientAwardEvidenceMatchStatus.AMBIGUOUS
    assert set(outcome.candidate_vendor_ids) == {v1.id, v2.id}


def test_ambiguous_tax_number_never_falls_through_to_try_name(db_session: Session) -> None:
    """Once the strongest signal (tax number) is ambiguous, the matcher
    must return AMBIGUOUS immediately -- it must never fall through to a
    weaker signal to "break the tie", even if the name would have
    resolved cleanly to a third, different vendor."""
    v1 = _make_vendor(db_session, name="Vendor One", tax_number="100000000000009")
    v2 = _make_vendor(db_session, name="Vendor Two", tax_number="100000000000009")
    _make_vendor(db_session, name="Unrelated Clean Match")

    outcome = match_vendor(
        db_session, vendor_tax_number="100000000000009", vendor_name="Unrelated Clean Match"
    )

    assert outcome.status == ClientAwardEvidenceMatchStatus.AMBIGUOUS
    assert set(outcome.candidate_vendor_ids) == {v1.id, v2.id}


def test_tax_number_with_no_match_falls_through_to_name(db_session: Session) -> None:
    """A tax number that matches nothing on file (e.g. an existing vendor
    record that predates tax-number tracking) is not itself a dead end --
    the weaker name signal still gets a chance."""
    vendor = _make_vendor(db_session, name="Legacy Vendor Co", tax_number=None)

    outcome = match_vendor(
        db_session, vendor_tax_number="999999999999999", vendor_name="Legacy Vendor Co"
    )

    assert outcome.status == ClientAwardEvidenceMatchStatus.MATCHED
    assert outcome.vendor.id == vendor.id
    assert outcome.matched_on == "name"


def test_soft_deleted_vendor_is_not_matched(db_session: Session) -> None:
    vendor = _make_vendor(db_session, name="Deleted Vendor Co")
    vendor.is_deleted = True
    db_session.flush()

    outcome = match_vendor(db_session, vendor_name="Deleted Vendor Co")

    assert outcome.status == ClientAwardEvidenceMatchStatus.UNMATCHED
