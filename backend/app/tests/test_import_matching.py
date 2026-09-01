from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Quotation
from app.services import client_service, project_service, quotation_service
from app.services.import_matching import suggest_client_matches, suggest_project_matches, suggest_quotation_matches
from app.services.import_service import confirm_import, stage_document


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


def test_suggest_quotation_matches_finds_existing_reference_with_date_and_total(
    db_session: Session, tmp_path
) -> None:
    """Uses the real VN/QU/412/18 archive scenario: an existing quotation
    is on file (Nov 21, 2018, SAR 168,495); a second document sharing the
    same reference is staged. The advisory match must expose the existing
    quotation's current date/total so a reviewer can compare before
    deciding, without merging or overwriting anything."""
    client = client_service.create_client(db_session, name="Ashtead Technology")
    project = project_service.create_project(db_session, name="Office Facilities Work", client_id=client.id)
    existing_document = _stage(
        db_session,
        tmp_path,
        "Quotation Number: VN/QU/412/18\nQuotation Date: 21/11/2018\nNet Amount: 168,495.00\n",
        name="existing.txt",
    )
    confirm_import(db_session, existing_document, client_id=client.id, project_id=project.id)

    new_document = _stage(
        db_session,
        tmp_path,
        "Quotation Number: VN/QU/412/18\nQuotation Date: 27/11/2018\nNet Amount: 151,955.00\n",
        name="revision.txt",
    )
    matches = suggest_quotation_matches(db_session, new_document.quotation_candidate)

    assert len(matches) == 1
    match = matches[0]
    assert match.reference_number == "VN/QU/412/18"
    assert match.current_version_date.isoformat() == "2018-11-21"
    assert match.current_version_total == Decimal("168495.00")
    assert match.project_name == "Office Facilities Work"
    assert match.client_name == "Ashtead Technology"

    # Purely advisory -- nothing was merged, overwritten, or otherwise
    # touched by asking for suggestions.
    assert len(quotation_service.list_versions_for_quotation(db_session, match.quotation.id)) == 1


def test_suggest_quotation_matches_returns_empty_when_no_reference_extracted(
    db_session: Session, tmp_path
) -> None:
    document = _stage(db_session, tmp_path, "Nothing structured here.\n")
    assert suggest_quotation_matches(db_session, document.quotation_candidate) == []


def test_suggest_quotation_matches_returns_empty_when_reference_is_new(db_session: Session, tmp_path) -> None:
    document = _stage(db_session, tmp_path, "Quotation Number: Q-BRAND-NEW-999\n")
    assert suggest_quotation_matches(db_session, document.quotation_candidate) == []


def test_suggest_quotation_matches_never_fuzzy_matches_a_suffixed_reference(
    db_session: Session, tmp_path
) -> None:
    """Real archive finding: VN/QU/396/18 (7 Nov, SAR 242,500) and
    VN/QU/396B/18 (11 Nov, SAR 192,750) are the same client, same subject,
    almost certainly a real revision -- but the reference strings differ.
    Matching must stay exact-string-only: no fuzzy/prefix matching that
    would treat "396" and "396B" as related, and no automatic merge or
    revision relationship. A human reviewer must be the one to notice and
    connect them (see IMPORT_ARCHITECTURE.md's documented limitation)."""
    client = client_service.create_client(db_session, name="ABT Company Ltd")
    project = project_service.create_project(db_session, name="Corrugated sheet work in Binex Office", client_id=client.id)
    existing_document = _stage(
        db_session,
        tmp_path,
        "Quotation Number: VN/QU/396/18\nQuotation Date: 07/11/2018\nNet Amount: 242,500.00\n",
        name="396.txt",
    )
    confirm_import(db_session, existing_document, client_id=client.id, project_id=project.id)

    new_document = _stage(
        db_session,
        tmp_path,
        "Quotation Number: VN/QU/396B/18\nQuotation Date: 11/11/2018\nNet Amount: 192,750.00\n",
        name="396b.txt",
    )
    matches = suggest_quotation_matches(db_session, new_document.quotation_candidate)

    assert matches == []
    # And confirming VN/QU/396B/18 creates an entirely independent
    # quotation -- never attached as a revision of VN/QU/396/18.
    version = confirm_import(db_session, new_document, client_id=client.id, project_id=project.id)
    assert version.quotation_id != existing_document.resulting_quotation_id
    all_quotations = db_session.query(Quotation).all()
    assert len(all_quotations) == 2
    assert {q.reference_number for q in all_quotations} == {"VN/QU/396/18", "VN/QU/396B/18"}
