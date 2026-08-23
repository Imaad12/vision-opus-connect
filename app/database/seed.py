"""Optional seed data for lookup tables.

`DEFAULT_COST_CATEGORIES` is plain data, not business logic — nothing in
`app/core/financial_engine.py` or the services layer hard-codes category
names or branches on them. Calling `seed_default_cost_categories()` is
optional and idempotent (by name); a business can rename, add, or remove
categories via `CostCategory` rows without touching any code.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CostCategory

DEFAULT_COST_CATEGORIES: tuple[str, ...] = (
    "Materials",
    "Labour",
    "Subcontractors",
    "Equipment",
    "Transport",
    "Plant",
    "Permits",
    "Professional Fees",
    "Other",
)


def seed_default_cost_categories(session: Session) -> list[CostCategory]:
    """Insert the default cost categories that don't already exist (by name).

    Safe to call repeatedly. Returns the newly created rows only.
    """
    existing_names = set(session.scalars(select(CostCategory.name)))
    created = [
        CostCategory(name=name) for name in DEFAULT_COST_CATEGORIES if name not in existing_names
    ]
    session.add_all(created)
    return created
