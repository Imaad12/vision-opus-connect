"""OPTIONAL development/test dataset — never run automatically.

This inserts fabricated projects for manually exercising the UI and
verifying that estimated-vs-actual figures compute correctly. It is
clearly separate from `app/database/seed.py` (which seeds real reference
data — cost categories — safe to run against a production database).

Run explicitly, and only against a development database:

    python -m app.database.dev_seed_data

Never imported by `app.ui.main` or any other production code path.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.enums import ProjectStatus
from app.database.seed import seed_default_cost_categories
from app.database.session import session_scope
from app.models import CostCategory
from app.services.client_service import create_client
from app.services.cost_service import add_actual_cost, add_estimated_cost_line, get_or_create_current_revision
from app.services.project_service import create_project
from app.services.quotation_service import create_quotation, mark_awarded, mark_lost


def create_dev_dataset() -> None:
    with session_scope() as session:
        seed_default_cost_categories(session)
        materials = session.query(CostCategory).filter_by(name="Materials").one()
        labour = session.query(CostCategory).filter_by(name="Labour").one()

        client = create_client(
            session,
            name="Acme Developers (DEV DATA)",
            contact_email="dev-data@example.test",
        )

        # Project A: awarded, under budget.
        project_a = create_project(
            session, name="[DEV] Villa Renovation A", client_id=client.id, project_code="DEV-A"
        )
        version_a = create_quotation(session, project_a, quoted_value=Decimal("1000000"))
        mark_awarded(session, version_a, contract_value=Decimal("1000000"))
        revision_a = get_or_create_current_revision(session, project_a)
        add_estimated_cost_line(
            session, project_a, revision_a, cost_category_id=materials.id, amount=Decimal("500000")
        )
        add_estimated_cost_line(
            session, project_a, revision_a, cost_category_id=labour.id, amount=Decimal("280000")
        )
        add_actual_cost(session, project_a, cost_category_id=materials.id, amount=Decimal("480000"))
        add_actual_cost(session, project_a, cost_category_id=labour.id, amount=Decimal("270000"))
        project_a.status = ProjectStatus.IN_PROGRESS

        # Project B: awarded, over budget.
        project_b = create_project(
            session, name="[DEV] Office Fitout B", client_id=client.id, project_code="DEV-B"
        )
        version_b = create_quotation(session, project_b, quoted_value=Decimal("1500000"))
        mark_awarded(session, version_b, contract_value=Decimal("1500000"))
        revision_b = get_or_create_current_revision(session, project_b)
        add_estimated_cost_line(
            session, project_b, revision_b, cost_category_id=materials.id, amount=Decimal("700000")
        )
        add_estimated_cost_line(
            session, project_b, revision_b, cost_category_id=labour.id, amount=Decimal("400000")
        )
        add_actual_cost(session, project_b, cost_category_id=materials.id, amount=Decimal("800000"))
        add_actual_cost(session, project_b, cost_category_id=labour.id, amount=Decimal("450000"))
        project_b.status = ProjectStatus.IN_PROGRESS

        # Project C: quotation only, never awarded — must never appear as revenue.
        project_c = create_project(
            session, name="[DEV] Warehouse Fitout C (quote only)", client_id=client.id, project_code="DEV-C"
        )
        version_c = create_quotation(session, project_c, quoted_value=Decimal("600000"))
        mark_lost(session, version_c)

    print("Development dataset created: DEV-A (under budget), DEV-B (over budget), DEV-C (lost quotation).")


if __name__ == "__main__":
    create_dev_dataset()
