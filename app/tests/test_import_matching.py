from __future__ import annotations

from sqlalchemy.orm import Session

from app.services import client_service, project_service
from app.services.import_matching import suggest_client_matches, suggest_project_matches
from app.services.import_service import stage_document


def _stage(session: Session, tmp_path, text: str, name: str = "quote.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return stage_document(session, path)


def test_suggest_project_matches_by_project_number(db_session: Session, tmp_path) -> None:
    client = client_service.create_client(db_session, name="ABC Holdings")
    project = project_service.create_project(
        db_session, name="Villa ABC Renovation", client_id=client.id, project_code="VC-2024-018"
    )

    document = _stage(db_session, tmp_path, "Project Number: VC-2024-018\n")
    matches = suggest_project_matches(db_session, document.quotation_candidate)

    assert project in matches


def test_suggest_project_matches_by_name_substring(db_session: Session, tmp_path) -> None:
    client = client_service.create_client(db_session, name="ABC Holdings")
    project = project_service.create_project(db_session, name="Villa ABC Renovation - Phase 2", client_id=client.id)

    document = _stage(db_session, tmp_path, "Project Name: Villa ABC Renovation\n")
    matches = suggest_project_matches(db_session, document.quotation_candidate)

    assert project in matches


def test_suggest_project_matches_returns_empty_when_nothing_to_go_on(db_session: Session, tmp_path) -> None:
    document = _stage(db_session, tmp_path, "Nothing structured here.\n")
    assert suggest_project_matches(db_session, document.quotation_candidate) == []


def test_suggest_client_matches_by_name_substring(db_session: Session, tmp_path) -> None:
    client = client_service.create_client(db_session, name="ABC Holdings LLC")

    document = _stage(db_session, tmp_path, "Client Name: ABC Holdings\n")
    matches = suggest_client_matches(db_session, document.quotation_candidate)

    assert client in matches


def test_suggest_client_matches_never_returns_deleted_clients(db_session: Session, tmp_path) -> None:
    client = client_service.create_client(db_session, name="ABC Holdings")
    client.is_deleted = True
    db_session.flush()

    document = _stage(db_session, tmp_path, "Client Name: ABC Holdings\n")
    matches = suggest_client_matches(db_session, document.quotation_candidate)

    assert client not in matches
