from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.enums import CostPaymentStatus
from app.models import CostCategory
from app.services.client_service import create_client
from app.services.cost_service import (
    add_actual_cost,
    add_estimated_cost_line,
    cost_by_category,
    get_or_create_current_revision,
    list_actual_costs,
    list_estimated_costs,
    mark_revision_final,
    net_amount_of,
    remove_estimated_cost_line,
    start_new_estimate_revision,
)
from app.services.errors import ValidationError
from app.services.financial_service import (
    get_final_estimate_revision,
    get_latest_estimate_revision,
    get_original_estimate_revision,
)
from app.services.project_service import create_project


def _project(session: Session):
    client_id = create_client(session, name="Acme Developers").id
    return create_project(session, name="Villa Renovation", client_id=client_id)


def _category(session: Session, name: str = "Materials") -> CostCategory:
    category = CostCategory(name=name)
    session.add(category)
    session.flush()
    return category


def test_add_estimated_cost_line_creates_revision_one_automatically(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)

    line = add_estimated_cost_line(
        db_session,
        project,
        get_or_create_current_revision(db_session, project),
        cost_category_id=category.id,
        description="Cement",
        amount=Decimal("780000"),
    )
    db_session.commit()

    revision = get_original_estimate_revision(db_session, project)
    assert revision.revision_number == 1
    assert line.estimate_revision_id == revision.id


def test_add_estimated_cost_line_computes_amount_from_quantity_and_rate(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)
    revision = get_or_create_current_revision(db_session, project)

    line = add_estimated_cost_line(
        db_session,
        project,
        revision,
        cost_category_id=category.id,
        quantity=Decimal("100"),
        unit_rate=Decimal("25.50"),
    )
    db_session.commit()

    assert line.amount == Decimal("2550.00")


def test_add_estimated_cost_line_requires_amount_or_quantity_and_rate(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)
    revision = get_or_create_current_revision(db_session, project)

    with pytest.raises(ValidationError):
        add_estimated_cost_line(db_session, project, revision, cost_category_id=category.id)


def test_add_estimated_cost_line_rejects_invalid_category(db_session: Session) -> None:
    project = _project(db_session)
    revision = get_or_create_current_revision(db_session, project)

    with pytest.raises(ValidationError):
        add_estimated_cost_line(
            db_session, project, revision, cost_category_id=999, amount=Decimal("1000")
        )


def test_cannot_add_line_to_a_historical_revision(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)
    first_revision = get_or_create_current_revision(db_session, project)
    add_estimated_cost_line(
        db_session, project, first_revision, cost_category_id=category.id, amount=Decimal("780000")
    )
    db_session.commit()

    start_new_estimate_revision(db_session, project, copy_forward=False)
    db_session.commit()

    with pytest.raises(ValidationError):
        add_estimated_cost_line(
            db_session, project, first_revision, cost_category_id=category.id, amount=Decimal("1")
        )


def test_cannot_remove_line_from_a_historical_revision(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)
    first_revision = get_or_create_current_revision(db_session, project)
    line = add_estimated_cost_line(
        db_session, project, first_revision, cost_category_id=category.id, amount=Decimal("780000")
    )
    db_session.commit()

    start_new_estimate_revision(db_session, project, copy_forward=False)
    db_session.commit()

    with pytest.raises(ValidationError):
        remove_estimated_cost_line(db_session, project, line)


def test_start_new_estimate_revision_copies_lines_forward(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)
    first_revision = get_or_create_current_revision(db_session, project)
    add_estimated_cost_line(
        db_session, project, first_revision, cost_category_id=category.id, amount=Decimal("780000")
    )
    db_session.commit()

    second_revision = start_new_estimate_revision(db_session, project)
    db_session.commit()

    assert second_revision.revision_number == 2
    copied_lines = list_estimated_costs(db_session, second_revision)
    assert len(copied_lines) == 1
    assert copied_lines[0].amount == Decimal("780000")
    # The original revision's own line is untouched, a separate row.
    original_lines = list_estimated_costs(db_session, first_revision)
    assert len(original_lines) == 1
    assert original_lines[0].id != copied_lines[0].id


def test_start_new_estimate_revision_without_copy_forward_is_empty(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)
    first_revision = get_or_create_current_revision(db_session, project)
    add_estimated_cost_line(
        db_session, project, first_revision, cost_category_id=category.id, amount=Decimal("780000")
    )
    db_session.commit()

    second_revision = start_new_estimate_revision(db_session, project, copy_forward=False)
    db_session.commit()

    assert list_estimated_costs(db_session, second_revision) == []


def test_mark_revision_final_clears_previous_final_flag(db_session: Session) -> None:
    project = _project(db_session)
    first_revision = get_or_create_current_revision(db_session, project)
    mark_revision_final(db_session, project, first_revision)
    second_revision = start_new_estimate_revision(db_session, project, copy_forward=False)
    db_session.commit()

    mark_revision_final(db_session, project, second_revision)
    db_session.commit()

    db_session.refresh(first_revision)
    db_session.refresh(second_revision)
    assert first_revision.is_final is False
    assert second_revision.is_final is True
    assert get_final_estimate_revision(db_session, project).id == second_revision.id


def test_add_actual_cost_and_net_amount(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)

    cost = add_actual_cost(
        db_session,
        project,
        cost_category_id=category.id,
        amount=Decimal("10500"),
        tax_amount=Decimal("500"),
        description="Steel delivery",
        payment_status=CostPaymentStatus.PAID,
    )
    db_session.commit()

    assert cost.amount == Decimal("10500")
    assert net_amount_of(cost) == Decimal("10000")
    assert list_actual_costs(db_session, project) == [cost]


def test_add_actual_cost_rejects_tax_exceeding_amount(db_session: Session) -> None:
    project = _project(db_session)
    category = _category(db_session)

    with pytest.raises(ValidationError):
        add_actual_cost(
            db_session, project, cost_category_id=category.id, amount=Decimal("1000"), tax_amount=Decimal("2000")
        )


def test_add_actual_cost_rejects_invalid_category(db_session: Session) -> None:
    project = _project(db_session)
    with pytest.raises(ValidationError):
        add_actual_cost(db_session, project, cost_category_id=999, amount=Decimal("1000"))


def test_cost_by_category_groups_and_respects_recoverable_tax(db_session: Session) -> None:
    project = _project(db_session)
    materials = _category(db_session, "Materials")
    labour = _category(db_session, "Labour")

    add_actual_cost(
        db_session, project, cost_category_id=materials.id, amount=Decimal("10500"), tax_amount=Decimal("500")
    )
    add_actual_cost(
        db_session,
        project,
        cost_category_id=materials.id,
        amount=Decimal("5250"),
        tax_amount=Decimal("250"),
        is_tax_recoverable=False,
    )
    add_actual_cost(db_session, project, cost_category_id=labour.id, amount=Decimal("2000"))
    db_session.commit()

    totals = dict((category.name, total) for category, total in cost_by_category(db_session, project))
    # Materials: (10500-500 recoverable) + 5250 (non-recoverable, full gross) = 15,250
    assert totals["Materials"] == Decimal("15250")
    assert totals["Labour"] == Decimal("2000")


def test_estimated_and_actual_costs_are_independent_data(db_session: Session) -> None:
    """Never overwrite an estimate with an actual cost — they are entirely
    separate tables/rows, verified end to end through the service layer."""
    project = _project(db_session)
    category = _category(db_session)
    revision = get_or_create_current_revision(db_session, project)
    add_estimated_cost_line(
        db_session, project, revision, cost_category_id=category.id, amount=Decimal("780000")
    )
    add_actual_cost(db_session, project, cost_category_id=category.id, amount=Decimal("750000"))
    db_session.commit()

    assert list_estimated_costs(db_session, revision)[0].amount == Decimal("780000")
    assert list_actual_costs(db_session, project)[0].amount == Decimal("750000")
    assert get_latest_estimate_revision(db_session, project).id == revision.id
