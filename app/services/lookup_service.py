"""Read-only lookups for UI selectors (cost categories, trades, vendors).

Categories/trades are plain data (see `app/database/seed.py`) — nothing
here or in the UI hard-codes a specific category name.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CostCategory, Trade, Vendor


def list_cost_categories(session: Session) -> list[CostCategory]:
    return list(session.execute(select(CostCategory).order_by(CostCategory.name)).scalars().all())


def list_trades(session: Session) -> list[Trade]:
    return list(session.execute(select(Trade).order_by(Trade.name)).scalars().all())


def list_vendors(session: Session) -> list[Vendor]:
    stmt = select(Vendor).where(Vendor.is_deleted.is_(False)).order_by(Vendor.name)
    return list(session.execute(stmt).scalars().all())
