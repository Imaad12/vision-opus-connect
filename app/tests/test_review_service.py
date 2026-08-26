"""Review-queue triage: needs_attention vs. ready_to_confirm."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.services.import_service import stage_document, stage_purchase_order_document
from app.services.review_service import list_purchase_order_review_queue, list_quotation_review_queue


def _write_quotation(tmp_path: Path, name: str, *, reference: str, net: str | None = "1,000.00") -> Path:
    lines = [f"Quotation Number: {reference}", "Quotation Date: 01/01/2025"]
    if net is not None:
        # VAT and gross are included alongside net so the candidate is
        # genuinely HIGH_CONFIDENCE end to end -- an undetermined VAT
        # (the real business rule: SAR 0.00, LOW confidence, applied
        # whenever a document doesn't state one) would otherwise flag
        # REVIEW_REQUIRED on every fixture that only sets `net`.
        lines.append(f"Net Amount: {net}")
        lines.append("VAT Amount: 0.00")
        lines.append(f"Total Including VAT: {net}")
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_po(tmp_path: Path, name: str, *, reference: str | None) -> Path:
    lines = []
    if reference is not None:
        lines.append(f"Quotation Reference: {reference}")
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_complete_high_confidence_quotation_is_ready_to_confirm(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation(tmp_path, "q.txt", reference="Q-001")
    stage_document(db_session, path)

    queue = list_quotation_review_queue(db_session)

    assert len(queue.ready_to_confirm) == 1
    assert queue.needs_attention == []
    assert queue.ready_to_confirm[0].filename == "q.txt"


def test_a_quotation_missing_a_mandatory_field_needs_attention(db_session: Session, tmp_path: Path) -> None:
    path = _write_quotation(tmp_path, "q.txt", reference="Q-002", net=None)
    stage_document(db_session, path)

    queue = list_quotation_review_queue(db_session)

    assert len(queue.needs_attention) == 1
    assert queue.ready_to_confirm == []


def test_a_matched_po_is_ready_to_confirm_without_further_extraction_review(
    db_session: Session, tmp_path: Path
) -> None:
    from app.services import client_service, project_service, quotation_service
    from decimal import Decimal

    client = client_service.create_client(db_session, name="Client")
    project = project_service.create_project(db_session, name="Project", client_id=client.id)
    quotation_service.create_quotation(
        db_session, project, reference_number="VN/QU/700/25", quoted_value=Decimal("1000.00")
    )

    path = _write_po(tmp_path, "po.txt", reference="VN/QU/700/25")
    stage_purchase_order_document(db_session, path)

    queue = list_purchase_order_review_queue(db_session)

    assert len(queue.ready_to_confirm) == 1
    assert queue.needs_attention == []


def test_an_unmatched_po_needs_attention(db_session: Session, tmp_path: Path) -> None:
    path = _write_po(tmp_path, "po.txt", reference="VN/QU/NO-MATCH/25")
    stage_purchase_order_document(db_session, path)

    queue = list_purchase_order_review_queue(db_session)

    assert len(queue.needs_attention) == 1
    assert queue.ready_to_confirm == []
    assert "UNMATCHED" in queue.needs_attention[0].reason


def test_a_po_with_no_reference_at_all_needs_attention(db_session: Session, tmp_path: Path) -> None:
    path = _write_po(tmp_path, "po.txt", reference=None)
    stage_purchase_order_document(db_session, path)

    queue = list_purchase_order_review_queue(db_session)

    assert len(queue.needs_attention) == 1


def test_confirmed_documents_never_appear_in_either_queue(db_session: Session, tmp_path: Path) -> None:
    from app.services import client_service, project_service
    from app.services.import_service import confirm_import

    path = _write_quotation(tmp_path, "q.txt", reference="Q-003")
    document = stage_document(db_session, path)
    client = client_service.create_client(db_session, name="Client")
    project = project_service.create_project(db_session, name="Project", client_id=client.id)
    confirm_import(db_session, document, client_id=client.id, project_id=project.id)

    queue = list_quotation_review_queue(db_session)

    assert queue.needs_attention == []
    assert queue.ready_to_confirm == []
