"""rename purchase order award evidence to client award evidence

The pre-existing `PurchaseOrder` model represented client-award evidence
(a client PO document confirming a quotation was awarded) -- a name
collision with the actual ERP concept of an outbound supplier purchase
order the VINCO frontend needs next. This migration renames the
award-evidence tables/columns/constraints only; no column types, data,
or business rules change. See app/models/client_award_evidence.py.

Revision ID: e0f5a430387f
Revises: f8324c133881
Create Date: 2026-08-27 11:19:34.578406

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0f5a430387f'
down_revision: Union[str, Sequence[str], None] = 'f8324c133881'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Table renames only -- modern SQLite (3.25+, what SQLAlchemy targets
    # here) automatically rewrites foreign-key references in *other*
    # tables' schema when the referenced table is renamed, verified by
    # migrating a populated database end-to-end (upgrade/downgrade/
    # upgrade) with `PRAGMA foreign_key_check` clean throughout. Renaming
    # the constraint *names* themselves is deliberately skipped: SQLite
    # batch mode does not reliably round-trip a custom name given to a
    # constraint created by a previous batch operation (confirmed by a
    # failed downgrade attempt during development of this migration), and
    # a constraint's internal name has no effect on application behavior
    # -- only the table/column names below are ever referenced by code.
    op.rename_table('purchase_orders', 'client_award_evidence')
    op.rename_table('imported_purchase_order_candidates', 'imported_client_award_evidence_candidates')

    with op.batch_alter_table('imported_documents', schema=None) as batch_op:
        batch_op.alter_column('resulting_purchase_order_id', new_column_name='resulting_client_award_evidence_id')


def downgrade() -> None:
    with op.batch_alter_table('imported_documents', schema=None) as batch_op:
        batch_op.alter_column('resulting_client_award_evidence_id', new_column_name='resulting_purchase_order_id')

    op.rename_table('imported_client_award_evidence_candidates', 'imported_purchase_order_candidates')
    op.rename_table('client_award_evidence', 'purchase_orders')
