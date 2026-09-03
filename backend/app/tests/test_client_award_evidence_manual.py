"""Tests for the manual "Record Client PO" path -- the hand-entered
counterpart to the OCR-import-confirmed award path already covered by
`test_client_award_evidence_service.py`. Covers:

- `client_award_evidence_service.record_client_award_evidence` /
  `attach_client_award_evidence_document` directly (service layer).
- The `/client-award-evidence*` and `/quotations/{id}/client-award-evidence`
  API routes end-to-end, including permission checks and the derived
  `variance`/`source`/`contracted` fields the frontend depends on.

Deliberately does not touch or re-test `confirm_client_award_evidence_import`
(the OCR path) or anything under `/purchase-orders` (the unrelated
Supplier Purchase Order domain) -- those already have their own coverage
and are out of scope here.
"""

from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.api.routers.client_award_evidence import _read as read_client_award_evidence
from app.services import client_service, project_service, quotation_service
from app.services.client_award_evidence_service import (
    attach_client_award_evidence_document,
    confirm_client_award_evidence_import,
    record_client_award_evidence,
)
from app.services.errors import ValidationError
from app.services.import_service import stage_client_award_evidence_document
from app.tests.api_test_support import make_api_client, make_memory_engine


# --------------------------------------------------------------- service layer


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    from sqlalchemy.orm import sessionmaker

    engine = make_memory_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    yield session
    session.close()
    engine.dispose()


def _create_quotation(session: Session, *, reference: str, quoted_value: Decimal | None = Decimal("50000.00")):
    client = client_service.create_client(session, name=f"Client for {reference}")
    project = project_service.create_project(session, name=f"Project for {reference}", client_id=client.id)
    version = quotation_service.create_quotation(
        session, project, reference_number=reference, quoted_value=quoted_value
    )
    quotation_service.mark_submitted(session, version)
    session.flush()
    return project, version


def test_record_client_award_evidence_falls_back_to_quoted_value(db_session: Session):
    project, version = _create_quotation(db_session, reference="Q-M-001")

    evidence = record_client_award_evidence(
        db_session, version.quotation, po_reference_number="  PO-M-001  ", net_value=None
    )

    db_session.flush()
    db_session.refresh(project)
    assert project.contract_value == Decimal("50000.00")
    assert project.winning_quotation_version_id == version.id
    assert evidence.po_reference_number == "PO-M-001"  # whitespace-normalized
    assert evidence.awarded_quotation_version_id == version.id


def test_record_client_award_evidence_stores_awarded_value_independently(db_session: Session):
    project, version = _create_quotation(db_session, reference="Q-M-002", quoted_value=Decimal("100000.00"))

    evidence = record_client_award_evidence(
        db_session,
        version.quotation,
        po_reference_number="PO-M-002",
        net_value=Decimal("95000.00"),
        tax_value=Decimal("14250.00"),
        gross_value=Decimal("109250.00"),
    )

    db_session.flush()
    db_session.refresh(project)
    # The award used the client's own value, not the quoted value --
    # and the quotation's quoted_value was never overwritten.
    assert project.contract_value == Decimal("95000.00")
    assert version.quoted_value == Decimal("100000.00")
    assert evidence.net_value == Decimal("95000.00")


def test_record_client_award_evidence_duplicate_reference_raises(db_session: Session):
    _, version = _create_quotation(db_session, reference="Q-M-003")
    record_client_award_evidence(db_session, version.quotation, po_reference_number="PO-M-003")

    with pytest.raises(ValidationError, match="already recorded"):
        record_client_award_evidence(db_session, version.quotation, po_reference_number="PO-M-003")


def test_record_client_award_evidence_second_po_after_award_does_not_reaward(db_session: Session):
    project, version = _create_quotation(db_session, reference="Q-M-004", quoted_value=Decimal("10000.00"))
    record_client_award_evidence(db_session, version.quotation, po_reference_number="PO-M-004-A")
    db_session.flush()
    db_session.refresh(project)
    first_contract_value = project.contract_value
    assert first_contract_value == Decimal("10000.00")

    # A second PO against the same, now-awarded quotation must be
    # recorded as additional evidence only -- never re-award.
    second = record_client_award_evidence(
        db_session, version.quotation, po_reference_number="PO-M-004-B", net_value=Decimal("999999.00")
    )

    db_session.flush()
    db_session.refresh(project)
    assert project.contract_value == first_contract_value
    assert second.awarded_quotation_version_id == version.id


def test_record_client_award_evidence_requires_a_usable_value(db_session: Session):
    _, version = _create_quotation(db_session, reference="Q-M-005", quoted_value=None)

    with pytest.raises(ValidationError, match="usable positive value"):
        record_client_award_evidence(db_session, version.quotation, po_reference_number="PO-M-005")


def test_record_client_award_evidence_blank_reference_raises(db_session: Session):
    _, version = _create_quotation(db_session, reference="Q-M-006")

    with pytest.raises(ValidationError, match="reference number is required"):
        record_client_award_evidence(db_session, version.quotation, po_reference_number="   ")


def test_attach_document_sets_provenance(db_session: Session, tmp_path):
    _, version = _create_quotation(db_session, reference="Q-M-007")
    evidence = record_client_award_evidence(db_session, version.quotation, po_reference_number="PO-M-007")

    pdf_path = tmp_path / "client-po.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake client po content")

    document = attach_client_award_evidence_document(
        db_session, evidence, pdf_path, original_filename="Client PO 007.pdf"
    )

    assert document.resulting_client_award_evidence_id == evidence.id
    assert document.filename == "Client PO 007.pdf"
    assert document.review_status.value == "CONFIRMED"


def test_source_is_manual_for_a_hand_typed_po_with_no_document(db_session: Session):
    _, version = _create_quotation(db_session, reference="Q-M-009")
    evidence = record_client_award_evidence(db_session, version.quotation, po_reference_number="PO-M-009")

    read = read_client_award_evidence(db_session, evidence)

    assert read.source == "manual"
    assert read.document is None


def test_source_stays_manual_when_a_document_is_attached_by_hand(db_session: Session, tmp_path):
    """Regression guard: attaching a PDF to a manually-recorded PO must
    not flip `source` to "imported" -- only a document that actually
    went through OCR extraction (a staged candidate) earns that label.
    A router bug once conflated "has *any* document" with "was OCR-
    imported", which would have mislabeled this exact scenario."""
    _, version = _create_quotation(db_session, reference="Q-M-010")
    evidence = record_client_award_evidence(db_session, version.quotation, po_reference_number="PO-M-010")
    pdf_path = tmp_path / "manually-attached.pdf"
    pdf_path.write_bytes(b"hand-attached pdf, never touched by OCR")
    attach_client_award_evidence_document(db_session, evidence, pdf_path, original_filename="scan.pdf")

    read = read_client_award_evidence(db_session, evidence)

    assert read.document is not None
    assert read.source == "manual"


def test_source_is_imported_for_an_ocr_confirmed_po(db_session: Session, tmp_path):
    """The genuine OCR path (`stage_client_award_evidence_document` ->
    `confirm_client_award_evidence_import`) must still report
    source="imported" -- the fix for the regression above must not
    also break the real signal it's meant to preserve."""
    _, version = _create_quotation(db_session, reference="Q-M-011", quoted_value=Decimal("55000.00"))
    po_path = tmp_path / "po.txt"
    po_path.write_text(
        "PO Date: 10/01/2025\nQuotation Reference: Q-M-011\nNet Amount: 55,000.00\n", encoding="utf-8"
    )

    document = stage_client_award_evidence_document(db_session, po_path)
    assert document.client_award_evidence_candidate is not None
    evidence = confirm_client_award_evidence_import(db_session, document)

    read = read_client_award_evidence(db_session, evidence)

    assert read.source == "imported"
    assert read.document is not None


def test_attach_document_rejects_duplicate_hash(db_session: Session, tmp_path):
    _, version = _create_quotation(db_session, reference="Q-M-008")
    evidence = record_client_award_evidence(db_session, version.quotation, po_reference_number="PO-M-008")

    pdf_path = tmp_path / "client-po.pdf"
    pdf_path.write_bytes(b"identical bytes for dedup check")
    attach_client_award_evidence_document(db_session, evidence, pdf_path, original_filename="first.pdf")

    pdf_path_2 = tmp_path / "client-po-2.pdf"
    pdf_path_2.write_bytes(b"identical bytes for dedup check")
    with pytest.raises(ValidationError, match="already uploaded"):
        attach_client_award_evidence_document(db_session, evidence, pdf_path_2, original_filename="second.pdf")


# --------------------------------------------------------------------- API layer


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    engine = make_memory_engine()
    granted = {
        "customers.view",
        "customers.create",
        "projects.view",
        "projects.create",
        "quotations.view",
        "quotations.create",
        "quotations.submit",
        "quotations.approve",
        "contracts.create",
        "purchasing.po_create",
    }
    yield from make_api_client(engine, granted)
    engine.dispose()


@pytest.fixture
def submitted_version(api_client: TestClient) -> dict:
    client = api_client.post("/clients", json={"name": "Riyadh Contracting Co."}).json()
    project = api_client.post(
        "/projects", json={"name": "Tower Fit-Out", "client_id": client["id"]}
    ).json()
    version = api_client.post(
        f"/projects/{project['id']}/quotations",
        json={"reference_number": "Q-API-001", "quoted_value": "200000.00"},
    ).json()
    api_client.post(f"/quotation-versions/{version['id']}/submit")
    return version


def test_record_client_award_evidence_via_api(api_client: TestClient, submitted_version: dict):
    quotation_id = submitted_version["quotation"]["id"]

    response = api_client.post(
        f"/quotations/{quotation_id}/client-award-evidence",
        json={
            "po_reference_number": "PO-API-001",
            "po_date": "2026-02-01",
            "net_value": "195000.00",
            "tax_value": "29250.00",
            "gross_value": "224250.00",
            "currency": "SAR",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["po_reference_number"] == "PO-API-001"
    assert body["quotation_reference_number"] == "Q-API-001"
    assert body["quoted_value"] == "200000.00"
    assert body["net_value"] == "195000.00"
    # variance = net_value - quoted_value
    assert Decimal(body["variance"]) == Decimal("-5000.00")
    assert body["source"] == "manual"
    assert body["contracted"] is False
    assert body["document"] is None

    # Now visible on the quotation's own list, and in the global list.
    for_quotation = api_client.get(f"/quotations/{quotation_id}/client-award-evidence")
    assert for_quotation.status_code == 200
    assert len(for_quotation.json()) == 1

    global_list = api_client.get("/client-award-evidence")
    assert global_list.status_code == 200
    assert any(e["po_reference_number"] == "PO-API-001" for e in global_list.json())


def test_record_client_award_evidence_requires_approve_permission(
    api_client: TestClient, submitted_version: dict
):
    api_client.granted.discard("quotations.approve")
    quotation_id = submitted_version["quotation"]["id"]

    response = api_client.post(
        f"/quotations/{quotation_id}/client-award-evidence",
        json={"po_reference_number": "PO-API-002"},
    )

    assert response.status_code == 403


def test_record_client_award_evidence_duplicate_via_api_is_422(
    api_client: TestClient, submitted_version: dict
):
    quotation_id = submitted_version["quotation"]["id"]
    api_client.post(
        f"/quotations/{quotation_id}/client-award-evidence",
        json={"po_reference_number": "PO-API-003"},
    )

    response = api_client.post(
        f"/quotations/{quotation_id}/client-award-evidence",
        json={"po_reference_number": "PO-API-003"},
    )

    assert response.status_code == 422


def test_client_award_evidence_never_appears_as_a_supplier_purchase_order(
    api_client: TestClient, submitted_version: dict
):
    """The core domain-separation guarantee (P10): recording a client
    award/PO must never create or appear as a Supplier Purchase Order."""
    quotation_id = submitted_version["quotation"]["id"]
    api_client.post(
        f"/quotations/{quotation_id}/client-award-evidence",
        json={"po_reference_number": "PO-API-004"},
    )

    supplier_pos = api_client.get("/purchase-orders")
    assert supplier_pos.status_code == 200
    assert supplier_pos.json() == []


def test_create_contract_after_client_po_recorded(api_client: TestClient, submitted_version: dict):
    quotation_id = submitted_version["quotation"]["id"]
    project_id = submitted_version["quotation"]["project"]["id"]
    recorded = api_client.post(
        f"/quotations/{quotation_id}/client-award-evidence",
        json={"po_reference_number": "PO-API-005", "net_value": "200000.00"},
    ).json()
    assert recorded["contracted"] is False

    contract_response = api_client.post(f"/projects/{project_id}/contracts", json={})
    assert contract_response.status_code == 201

    # The evidence row now reports contracted=True.
    refreshed = api_client.get(f"/client-award-evidence/{recorded['id']}")
    assert refreshed.json()["contracted"] is True


def test_attach_document_via_api(api_client: TestClient, submitted_version: dict):
    quotation_id = submitted_version["quotation"]["id"]
    recorded = api_client.post(
        f"/quotations/{quotation_id}/client-award-evidence",
        json={"po_reference_number": "PO-API-006"},
    ).json()

    response = api_client.post(
        f"/client-award-evidence/{recorded['id']}/document",
        files={"file": ("client-po.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document"] is not None
    assert body["document"]["filename"] == "client-po.pdf"
    # Manually attaching a PDF to a hand-typed PO must NOT be mislabeled
    # as OCR-imported -- no extraction/candidate pipeline ever touched
    # it (see the router's `_read` helper).
    assert body["source"] == "manual"
