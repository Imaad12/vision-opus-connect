from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Currency, ProjectStatus
from app.services.client_service import create_client
from app.services.errors import ValidationError
from app.services.project_service import (
    create_project,
    get_or_create_default_company,
    get_project,
    list_projects,
    list_projects_with_snapshots,
    update_project,
)


def _client(session: Session, name: str = "Acme Developers") -> int:
    return create_client(session, name=name).id


def test_get_or_create_default_company_is_idempotent(db_session: Session) -> None:
    first = get_or_create_default_company(db_session)
    second = get_or_create_default_company(db_session)
    assert first.id == second.id


def test_create_project_requires_name(db_session: Session) -> None:
    client_id = _client(db_session)
    with pytest.raises(ValidationError):
        create_project(db_session, name="  ", client_id=client_id)


def test_create_project_requires_valid_client(db_session: Session) -> None:
    with pytest.raises(ValidationError):
        create_project(db_session, name="Villa Renovation", client_id=999)


def test_create_project_defaults_currency_to_aed(db_session: Session) -> None:
    client_id = _client(db_session)
    project = create_project(db_session, name="Villa Renovation", client_id=client_id)
    db_session.commit()

    assert project.contract_currency == Currency.AED
    assert project.contract_value is None  # no fake financial defaults
    assert project.status == ProjectStatus.LEAD


def test_create_project_rejects_duplicate_project_code(db_session: Session) -> None:
    client_id = _client(db_session)
    create_project(db_session, name="Villa A", client_id=client_id, project_code="PRJ-001")
    db_session.commit()

    with pytest.raises(ValidationError):
        create_project(db_session, name="Villa B", client_id=client_id, project_code="PRJ-001")


def test_create_project_validates_date_ordering(db_session: Session) -> None:
    client_id = _client(db_session)
    with pytest.raises(ValidationError):
        create_project(
            db_session,
            name="Villa Renovation",
            client_id=client_id,
            start_date=date(2026, 6, 1),
            planned_completion_date=date(2026, 1, 1),
        )


def test_update_project(db_session: Session) -> None:
    client_id = _client(db_session)
    project = create_project(db_session, name="Villa Renovation", client_id=client_id)
    db_session.commit()

    update_project(
        db_session,
        project,
        name="Villa Renovation Phase 2",
        client_id=client_id,
        status=ProjectStatus.TENDERING,
        description="Updated scope",
    )
    db_session.commit()

    fetched = get_project(db_session, project.id)
    assert fetched.name == "Villa Renovation Phase 2"
    assert fetched.status == ProjectStatus.TENDERING
    assert fetched.description == "Updated scope"


def test_list_projects_search_matches_name_code_and_client(db_session: Session) -> None:
    client_id = _client(db_session, "Acme Developers")
    create_project(db_session, name="Villa Renovation", client_id=client_id, project_code="PRJ-001")
    other_client_id = _client(db_session, "Beta Holdings")
    create_project(db_session, name="Office Fitout", client_id=other_client_id, project_code="PRJ-002")
    db_session.commit()

    assert [p.name for p in list_projects(db_session, search="villa")] == ["Villa Renovation"]
    assert [p.name for p in list_projects(db_session, search="PRJ-002")] == ["Office Fitout"]
    assert [p.name for p in list_projects(db_session, search="beta")] == ["Office Fitout"]


def test_list_projects_status_filter(db_session: Session) -> None:
    client_id = _client(db_session)
    create_project(db_session, name="Villa A", client_id=client_id, status=ProjectStatus.LEAD)
    create_project(db_session, name="Villa B", client_id=client_id, status=ProjectStatus.IN_PROGRESS)
    db_session.commit()

    results = list_projects(db_session, status=ProjectStatus.IN_PROGRESS)
    assert [p.name for p in results] == ["Villa B"]


def test_list_projects_with_snapshots_returns_a_snapshot_per_project(db_session: Session) -> None:
    client_id = _client(db_session)
    create_project(db_session, name="Villa A", client_id=client_id)
    create_project(db_session, name="Villa B", client_id=client_id)
    db_session.commit()

    pairs = list_projects_with_snapshots(db_session)
    assert len(pairs) == 2
    for project, snapshot in pairs:
        assert snapshot.currency == project.contract_currency
        assert snapshot.awarded_contract_value is None
