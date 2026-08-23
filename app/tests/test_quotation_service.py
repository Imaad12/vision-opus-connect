from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.enums import ProjectStatus, QuotationStatus
from app.services.client_service import create_client
from app.services.errors import ValidationError
from app.services.project_service import create_project, get_project
from app.services.quotation_service import (
    create_quotation,
    create_quotation_revision,
    list_quotation_versions,
    list_quotations_for_project,
    list_versions_for_quotation,
    mark_awarded,
    mark_lost,
    mark_submitted,
)


def _project(session: Session, name: str = "Villa Renovation"):
    client_id = create_client(session, name="Acme Developers").id
    return create_project(session, name=name, client_id=client_id)


def test_create_quotation_creates_version_one(db_session: Session) -> None:
    project = _project(db_session)
    version = create_quotation(
        db_session, project, reference_number="Q-001", quoted_value=Decimal("1000000")
    )
    db_session.commit()

    assert version.version_number == 1
    assert version.status == QuotationStatus.DRAFT
    assert version.quoted_value == Decimal("1000000")
    assert version.quotation.project_id == project.id


def test_create_quotation_rejects_negative_value(db_session: Session) -> None:
    project = _project(db_session)
    with pytest.raises(ValidationError):
        create_quotation(db_session, project, quoted_value=Decimal("-1"))


def test_create_quotation_rejects_duplicate_reference(db_session: Session) -> None:
    project = _project(db_session)
    create_quotation(db_session, project, reference_number="Q-001")
    db_session.commit()

    with pytest.raises(ValidationError):
        create_quotation(db_session, project, reference_number="Q-001")


def test_create_quotation_revision_increments_version_number(db_session: Session) -> None:
    project = _project(db_session)
    version1 = create_quotation(db_session, project, quoted_value=Decimal("1000000"))
    db_session.commit()

    version2 = create_quotation_revision(db_session, version1.quotation, quoted_value=Decimal("950000"))
    db_session.commit()

    versions = list_versions_for_quotation(db_session, version1.quotation_id)
    assert [v.version_number for v in versions] == [1, 2]
    assert version2.quoted_value == Decimal("950000")


def test_mark_submitted_updates_project_status(db_session: Session) -> None:
    project = _project(db_session)
    version = create_quotation(db_session, project, quoted_value=Decimal("1000000"))
    db_session.commit()

    mark_submitted(db_session, version)
    db_session.commit()

    assert version.status == QuotationStatus.SUBMITTED
    assert get_project(db_session, project.id).status == ProjectStatus.SUBMITTED


def test_mark_lost_does_not_touch_contract_value(db_session: Session) -> None:
    project = _project(db_session)
    version = create_quotation(db_session, project, quoted_value=Decimal("1000000"))
    db_session.commit()

    mark_lost(db_session, version)
    db_session.commit()

    assert version.status == QuotationStatus.LOST
    # A lost quotation must never appear as awarded/actual revenue.
    assert get_project(db_session, project.id).contract_value is None


def test_mark_awarded_sets_contract_value_and_links_winning_version(db_session: Session) -> None:
    project = _project(db_session)
    version = create_quotation(db_session, project, quoted_value=Decimal("1000000"))
    db_session.commit()

    mark_awarded(db_session, version, contract_value=Decimal("950000"))
    db_session.commit()

    updated_project = get_project(db_session, project.id)
    assert updated_project.contract_value == Decimal("950000")
    assert updated_project.winning_quotation_version_id == version.id
    assert updated_project.status == ProjectStatus.AWARDED
    assert version.status == QuotationStatus.WON


def test_mark_awarded_rejects_non_positive_value(db_session: Session) -> None:
    project = _project(db_session)
    version = create_quotation(db_session, project, quoted_value=Decimal("1000000"))
    db_session.commit()

    with pytest.raises(ValidationError):
        mark_awarded(db_session, version, contract_value=Decimal("0"))


def test_mark_awarded_twice_is_rejected(db_session: Session) -> None:
    project = _project(db_session)
    version = create_quotation(db_session, project, quoted_value=Decimal("1000000"))
    db_session.commit()
    mark_awarded(db_session, version, contract_value=Decimal("950000"))
    db_session.commit()

    other_version = create_quotation_revision(db_session, version.quotation, quoted_value=Decimal("960000"))
    db_session.commit()

    with pytest.raises(ValidationError):
        mark_awarded(db_session, other_version, contract_value=Decimal("960000"))


def test_list_quotations_for_project(db_session: Session) -> None:
    project = _project(db_session)
    create_quotation(db_session, project, reference_number="Q-001")
    create_quotation(db_session, project, reference_number="Q-002")
    db_session.commit()

    quotations = list_quotations_for_project(db_session, project.id)
    assert {q.reference_number for q in quotations} == {"Q-001", "Q-002"}


def test_list_quotation_versions_search(db_session: Session) -> None:
    project_a = _project(db_session, "Villa Renovation")
    project_b = _project(db_session, "Office Fitout")
    create_quotation(db_session, project_a, reference_number="Q-VILLA")
    create_quotation(db_session, project_b, reference_number="Q-OFFICE")
    db_session.commit()

    results = list_quotation_versions(db_session, search="villa")
    assert len(results) == 1
    assert results[0].quotation.reference_number == "Q-VILLA"
