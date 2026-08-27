"""Analytics calculations against known, hand-computed fixture data.

Fixture built directly via the service layer / ORM (not the import
pipeline — that's already covered by other test files) so every expected
number below is exactly derivable by hand; see the inline comments next
to each assertion for the arithmetic.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import Currency, ClientAwardEvidenceMatchStatus
from app.models import ImportedDocument, ImportedClientAwardEvidenceCandidate, ClientAwardEvidence
from app.services import analytics_service as a
from app.services import client_service, project_service, quotation_service


def _build_fixture(session: Session):
    client_a = client_service.create_client(session, name="Client A")
    client_b = client_service.create_client(session, name="Client B")

    project_a1 = project_service.create_project(session, name="A1", client_id=client_a.id)
    project_a2 = project_service.create_project(session, name="A2", client_id=client_a.id)
    project_b1 = project_service.create_project(session, name="B1", client_id=client_b.id)
    project_b2 = project_service.create_project(session, name="B2", client_id=client_b.id)

    # Q1: Client A, awarded, has a PO. Quoted 10,000 AED, awarded at
    # 12,000 AED (negotiated up), issued 2024-01-15.
    v1 = quotation_service.create_quotation(
        session, project_a1, reference_number="Q-A1", quoted_value=Decimal("10000.00"),
        currency=Currency.AED, issued_date=date(2024, 1, 15),
    )
    quotation_service.mark_awarded(session, v1, contract_value=Decimal("12000.00"))

    # Q2: Client A, not awarded, no PO. Quoted 5,000 AED, issued 2024-03-10.
    quotation_service.create_quotation(
        session, project_a2, reference_number="Q-A2", quoted_value=Decimal("5000.00"),
        currency=Currency.AED, issued_date=date(2024, 3, 10),
    )

    # Q3: Client B, missing quoted value entirely, not awarded, no PO.
    quotation_service.create_quotation(
        session, project_b1, reference_number="Q-B1", quoted_value=None,
        currency=Currency.AED, issued_date=date(2024, 1, 20),
    )

    # Q5: Client B, awarded (no negotiation change), has a PO. Quoted and
    # awarded 20,000 SAR, issued 2023-12-01.
    v5 = quotation_service.create_quotation(
        session, project_b2, reference_number="Q-B2", quoted_value=Decimal("20000.00"),
        currency=Currency.SAR, issued_date=date(2023, 12, 1),
    )
    quotation_service.mark_awarded(session, v5, contract_value=Decimal("20000.00"))

    # ClientAwardEvidence rows constructed directly (not via confirm_client_award_evidence_import
    # -- that flow is covered elsewhere; here the fixture needs full control
    # over independent field values to test the analytics arithmetic).
    po1 = ClientAwardEvidence(
        quotation_id=v1.quotation_id, awarded_quotation_version_id=v1.id,
        po_reference_number="Q-A1", po_date=date(2024, 1, 25),
        net_value=Decimal("9000.00"), tax_value=Decimal("450.00"), gross_value=Decimal("9450.00"),
        currency=Currency.AED,
    )
    po2 = ClientAwardEvidence(
        quotation_id=v5.quotation_id, awarded_quotation_version_id=v5.id,
        po_reference_number="Q-B2", po_date=date(2023, 12, 16),
        net_value=None, tax_value=None, gross_value=None,
        currency=Currency.SAR,
    )
    session.add_all([po1, po2])

    # One staged-but-unmatched PO candidate, unrelated to any of the above.
    document = ImportedDocument(
        original_path="/tmp/unrelated_po.pdf", filename="unrelated_po.pdf", extension="pdf",
        file_size=1, file_hash="deadbeef" * 8,
    )
    session.add(document)
    session.flush()
    session.add(
        ImportedClientAwardEvidenceCandidate(
            imported_document_id=document.id,
            po_reference_number="Q-NO-MATCH",
            match_status=ClientAwardEvidenceMatchStatus.UNMATCHED,
        )
    )
    session.flush()


def test_quotation_pipeline_summary(db_session: Session) -> None:
    _build_fixture(db_session)

    summary = a.compute_quotation_pipeline_summary(db_session)

    assert summary.quotation_count == 4
    assert summary.quotations_missing_value_count == 1  # Q3
    assert summary.quoted_value_total == Decimal("35000.00")  # 10000 + 5000 + 20000
    assert summary.average_quotation_value == Decimal("35000.00") / 3
    assert summary.awarded_quotation_count == 2  # Q1, Q5
    assert summary.awarded_value_total == Decimal("32000.00")  # 12000 + 20000
    assert summary.quotations_with_po_count == 2
    assert summary.quotations_without_po_count == 2  # Q2, Q3
    assert summary.quotation_to_po_conversion_rate == Decimal("2") / Decimal("4")


def test_client_performance(db_session: Session) -> None:
    _build_fixture(db_session)

    performance = {p.client_name: p for p in a.compute_client_performance(db_session)}

    assert performance["Client A"].quotation_count == 2
    assert performance["Client A"].quoted_value_total == Decimal("15000.00")
    assert performance["Client A"].awarded_count == 1
    assert performance["Client A"].awarded_value_total == Decimal("12000.00")

    assert performance["Client B"].quotation_count == 2
    assert performance["Client B"].quoted_value_total == Decimal("20000.00")  # Q3 excluded (no value)
    assert performance["Client B"].awarded_count == 1
    assert performance["Client B"].awarded_value_total == Decimal("20000.00")


def test_project_performance(db_session: Session) -> None:
    _build_fixture(db_session)

    performance = {p.project_name: p for p in a.compute_project_performance(db_session)}

    assert len(performance) == 4
    assert performance["A1"].quotation_count == 1
    assert performance["A1"].contract_value == Decimal("12000.00")
    assert performance["B1"].quoted_value_total == Decimal("0")  # Q3's missing value contributes nothing


def test_monthly_and_yearly_trends(db_session: Session) -> None:
    _build_fixture(db_session)

    monthly = {t.period: t for t in a.compute_monthly_trends(db_session)}
    assert monthly["2024-01"].quotation_count == 2  # Q1, Q3 (both issued 2024-01)
    assert monthly["2024-01"].quoted_value_total == Decimal("10000.00")  # Q3 excluded
    assert monthly["2024-01"].awarded_count == 1
    assert monthly["2024-01"].awarded_value_total == Decimal("12000.00")
    assert monthly["2023-12"].quotation_count == 1
    assert monthly["2023-12"].awarded_value_total == Decimal("20000.00")

    yearly = {t.period: t for t in a.compute_yearly_trends(db_session)}
    assert yearly["2024"].quotation_count == 3  # Q1, Q2, Q3
    assert yearly["2024"].quoted_value_total == Decimal("15000.00")
    assert yearly["2023"].quotation_count == 1
    assert yearly["2023"].quoted_value_total == Decimal("20000.00")


def test_average_time_to_po(db_session: Session) -> None:
    _build_fixture(db_session)

    timing = a.compute_average_time_to_po(db_session)

    # PO1: 2024-01-25 - 2024-01-15 = 10 days. PO2: 2023-12-16 - 2023-12-01 = 15 days.
    assert timing.sample_size == 2
    assert timing.average_days == Decimal("12.5")


def test_quotations_without_po(db_session: Session) -> None:
    _build_fixture(db_session)

    without_po = {q.reference_number for q in a.list_quotations_without_po(db_session)}

    assert without_po == {"Q-A2", "Q-B1"}


def test_unmatched_client_award_evidence(db_session: Session) -> None:
    _build_fixture(db_session)

    unmatched = a.list_unmatched_client_award_evidence_candidates(db_session)
    assert len(unmatched) == 1
    assert unmatched[0].po_reference_number == "Q-NO-MATCH"

    pending = a.compute_pending_client_award_evidence_summary(db_session)
    assert pending.unmatched_count == 1
    assert pending.ambiguous_count == 0


def test_po_financial_analysis(db_session: Session) -> None:
    _build_fixture(db_session)

    analysis = a.compute_po_financial_analysis(db_session)

    assert analysis.client_award_evidence_count == 2
    assert analysis.net_value_sample_size == 1  # only PO1 has a net_value
    assert analysis.net_value_total == Decimal("9000.00")
    assert analysis.tax_value_sample_size == 1
    assert analysis.tax_value_total == Decimal("450.00")
    assert analysis.gross_value_sample_size == 1
    assert analysis.gross_value_total == Decimal("9450.00")


def test_currency_breakdowns(db_session: Session) -> None:
    _build_fixture(db_session)

    quotation_breakdown = {b.currency: b for b in a.compute_quotation_currency_breakdown(db_session)}
    assert quotation_breakdown[Currency.AED].document_count == 3  # Q1, Q2, Q3
    assert quotation_breakdown[Currency.AED].value_total == Decimal("15000.00")  # Q3 excluded
    assert quotation_breakdown[Currency.SAR].document_count == 1
    assert quotation_breakdown[Currency.SAR].value_total == Decimal("20000.00")

    po_breakdown = {b.currency: b for b in a.compute_po_currency_breakdown(db_session)}
    assert po_breakdown[Currency.AED].document_count == 1
    assert po_breakdown[Currency.AED].value_total == Decimal("9000.00")
    assert po_breakdown[Currency.SAR].document_count == 1
    assert po_breakdown[Currency.SAR].value_total == Decimal("0")  # PO2's net_value is None


def test_pipeline_summary_with_no_data_at_all_is_safe(db_session: Session) -> None:
    summary = a.compute_quotation_pipeline_summary(db_session)

    assert summary.quotation_count == 0
    assert summary.quoted_value_total == Decimal("0")
    assert summary.average_quotation_value is None
    assert summary.quotation_to_po_conversion_rate is None

    timing = a.compute_average_time_to_po(db_session)
    assert timing.sample_size == 0
    assert timing.average_days is None
