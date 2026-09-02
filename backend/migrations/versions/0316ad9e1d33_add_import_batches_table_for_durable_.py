"""add import batches table for durable batch tracking

Revision ID: 0316ad9e1d33
Revises: 6d263c6d93a5
Create Date: 2026-09-02 17:49:00.982309

Hand-trimmed from the raw `alembic revision --autogenerate` output: that
run, against a fresh SQLite database, also proposed dropping/re-adding a
long list of indexes and constraints on unrelated tables (actual_costs,
boq_line_items, contacts, contracts, ...) and "type changes" on
imported_documents' own pre-existing enum columns -- none of that is a
real schema difference; it's SQLite's autogenerate reflecting
`native_enum=False` string columns and existing indexes slightly
differently than the ORM models declare them. Only the two genuinely new
things (the `import_batches` table and `imported_documents.batch_id`)
are kept here -- see `app.models.import_staging.ImportBatch`'s docstring
for what this adds and why.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0316ad9e1d33'
down_revision: Union[str, Sequence[str], None] = '6d263c6d93a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'import_batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=True),
        sa.Column('staged_count', sa.Integer(), nullable=False),
        sa.Column('resumed_count', sa.Integer(), nullable=False),
        sa.Column('skipped_duplicate_count', sa.Integer(), nullable=False),
        sa.Column('failed_count', sa.Integer(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('imported_documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('batch_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_imported_documents_batch_id_import_batches', 'import_batches', ['batch_id'], ['id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imported_documents', schema=None) as batch_op:
        batch_op.drop_constraint('fk_imported_documents_batch_id_import_batches', type_='foreignkey')
        batch_op.drop_column('batch_id')

    op.drop_table('import_batches')
