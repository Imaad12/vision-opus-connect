"""add indexes for high-traffic foreign key filters

Revision ID: 3ebcc85f8771
Revises: 926e160784a0
Create Date: 2026-08-31 20:59:59.190207

Additive only: CREATE INDEX exclusively, no DROP/ALTER/rename, no data
touched, no change to any primary key or foreign key relationship. Every
table/column below was confirmed (not guessed) by grepping actual
`.where(...)`/`.join(...)` clauses in app/services/*.py -- this is the
"Group A: definitely needed now" tier from the query-driven index audit,
not a blanket "index every FK" pass (the audit found 86 FK columns
total; only the 16 below currently appear in a real query filter or
join predicate). See the audit report for the full A/B/C breakdown.

Every VINCO table is schema-unqualified in every migration in this
chain (see app/database/schema_isolation.py) -- these CREATE INDEX
statements land in whatever schema `SET search_path` pinned before this
migration ran (`vinco` by default, see app/core/config.py), exactly
like every table-creation statement in 926e160784a0. `public` is never
referenced here.

Plain CREATE INDEX (not CONCURRENTLY): every VINCO table is currently
empty or near-empty in production, so there's no meaningful lock
contention to avoid, and CONCURRENTLY cannot run inside a transaction
block at all -- Alembic's default online-migration mode wraps upgrade()
in one (see migrations/env.py's `context.begin_transaction()`). Once
production tables hold enough real data that a brief ACCESS SHARE lock
during index creation would actually matter, a *future* index migration
should instead use `with op.get_context().autocommit_block():` around
`op.create_index(..., postgresql_concurrently=True)` for each new index
outside Alembic's wrapping transaction -- not needed for this one.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3ebcc85f8771'
down_revision: Union[str, Sequence[str], None] = '926e160784a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (index_name, table_name, column_name) -- every one confirmed present
# in an actual .where()/.join() clause in app/services/*.py.
_INDEXES: list[tuple[str, str, str]] = [
    ("ix_projects_client_id", "projects", "client_id"),
    ("ix_contacts_client_id", "contacts", "client_id"),
    ("ix_quotations_project_id", "quotations", "project_id"),
    ("ix_quotation_versions_quotation_id", "quotation_versions", "quotation_id"),
    ("ix_invoices_project_id", "invoices", "project_id"),
    ("ix_invoices_vendor_id", "invoices", "vendor_id"),
    ("ix_payments_invoice_id", "payments", "invoice_id"),
    ("ix_actual_costs_project_id", "actual_costs", "project_id"),
    ("ix_purchase_requests_project_id", "purchase_requests", "project_id"),
    ("ix_purchase_orders_project_id", "purchase_orders", "project_id"),
    ("ix_estimate_revisions_project_id", "estimate_revisions", "project_id"),
    ("ix_estimated_costs_estimate_revision_id", "estimated_costs", "estimate_revision_id"),
    ("ix_contracts_project_id", "contracts", "project_id"),
    ("ix_receipts_purchase_order_id", "receipts", "purchase_order_id"),
    ("ix_payroll_records_employee_id", "payroll_records", "employee_id"),
    ("ix_boq_line_items_boq_id", "boq_line_items", "boq_id"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for index_name, table_name, column_name in _INDEXES:
        op.create_index(index_name, table_name, [column_name])


def downgrade() -> None:
    """Downgrade schema."""
    for index_name, table_name, _column_name in reversed(_INDEXES):
        op.drop_index(index_name, table_name=table_name)
