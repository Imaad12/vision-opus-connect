from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import ProjectStatus
from app.models import CostCategory
from app.services.client_service import create_client
from app.services.cost_service import add_actual_cost, add_estimated_cost_line, get_or_create_current_revision
from app.services.dashboard_service import build_dashboard_summary
from app.services.project_service import create_project
from app.services.quotation_service import create_quotation, mark_awarded, mark_lost


def _client(session: Session) -> int:
    return create_client(session, name="Acme Developers").id


def test_empty_portfolio(db_session: Session) -> None:
    summary = build_dashboard_summary(db_session)

    assert summary.total_projects == 0
    assert summary.active_projects == 0
    assert summary.completed_projects == 0
    assert summary.total_awarded_contract_value == Decimal("0")
    assert summary.total_actual_cost == Decimal("0")
    assert summary.average_actual_margin is None
    assert summary.average_estimated_margin is None


def test_project_counts_by_status(db_session: Session) -> None:
    client_id = _client(db_session)
    p1 = create_project(db_session, name="Villa A", client_id=client_id, status=ProjectStatus.LEAD)
    p2 = create_project(db_session, name="Villa B", client_id=client_id, status=ProjectStatus.IN_PROGRESS)
    p3 = create_project(db_session, name="Villa C", client_id=client_id, status=ProjectStatus.COMPLETED)
    db_session.commit()

    summary = build_dashboard_summary(db_session)

    assert summary.total_projects == 3
    assert summary.active_projects == 2  # LEAD + IN_PROGRESS
    assert summary.completed_projects == 1


def test_lost_quotation_does_not_contribute_awarded_value(db_session: Session) -> None:
    client_id = _client(db_session)
    project = create_project(db_session, name="Villa A", client_id=client_id)
    version = create_quotation(db_session, project, quoted_value=Decimal("1000000"))
    mark_lost(db_session, version)
    db_session.commit()

    summary = build_dashboard_summary(db_session)
    assert summary.total_awarded_contract_value == Decimal("0")


def test_totals_sum_across_awarded_projects(db_session: Session) -> None:
    client_id = _client(db_session)
    category = CostCategory(name="Materials")
    db_session.add(category)
    db_session.flush()

    project_a = create_project(db_session, name="Villa A", client_id=client_id)
    version_a = create_quotation(db_session, project_a, quoted_value=Decimal("1000000"))
    mark_awarded(db_session, version_a, contract_value=Decimal("1000000"))
    revision_a = get_or_create_current_revision(db_session, project_a)
    add_estimated_cost_line(
        db_session, project_a, revision_a, cost_category_id=category.id, amount=Decimal("780000")
    )
    add_actual_cost(db_session, project_a, cost_category_id=category.id, amount=Decimal("750000"))

    project_b = create_project(db_session, name="Villa B", client_id=client_id)
    version_b = create_quotation(db_session, project_b, quoted_value=Decimal("1500000"))
    mark_awarded(db_session, version_b, contract_value=Decimal("1500000"))
    revision_b = get_or_create_current_revision(db_session, project_b)
    add_estimated_cost_line(
        db_session, project_b, revision_b, cost_category_id=category.id, amount=Decimal("1100000")
    )
    add_actual_cost(db_session, project_b, cost_category_id=category.id, amount=Decimal("1250000"))
    db_session.commit()

    summary = build_dashboard_summary(db_session)

    assert summary.total_awarded_contract_value == Decimal("2500000")
    assert summary.total_actual_cost == Decimal("2000000")
    # Project A profit: 1,000,000-750,000=250,000; Project B: 1,500,000-1,250,000=250,000
    assert summary.total_actual_profit == Decimal("500000")
    assert summary.average_actual_margin is not None


def test_average_margin_excludes_projects_without_revenue(db_session: Session) -> None:
    client_id = _client(db_session)
    category = CostCategory(name="Materials")
    db_session.add(category)
    db_session.flush()

    awarded_project = create_project(db_session, name="Villa A", client_id=client_id)
    version = create_quotation(db_session, awarded_project, quoted_value=Decimal("1000000"))
    mark_awarded(db_session, version, contract_value=Decimal("1000000"))
    add_actual_cost(db_session, awarded_project, cost_category_id=category.id, amount=Decimal("750000"))

    # A project with no award yet has no actual margin and must not drag
    # the average toward 0%.
    create_project(db_session, name="Villa B (lead only)", client_id=client_id)
    db_session.commit()

    summary = build_dashboard_summary(db_session)
    # Only one project has a defined margin: (1,000,000-750,000)/1,000,000*100 = 25%
    assert summary.average_actual_margin == Decimal("25.00")
