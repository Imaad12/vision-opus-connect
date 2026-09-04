"""add import_jobs durable queue, batch lifecycle columns, document storage refs

Revision ID: 7a1c9e2f5b3d
Revises: 0316ad9e1d33
Create Date: 2026-09-04 00:00:00.000000

Production-reliability follow-up to the historical-import pipeline
(see backend/IMPORT_ARCHITECTURE.md, this feature's own report):

- `import_jobs` is the durable, database-backed queue that replaces
  FastAPI `BackgroundTasks` as the mechanism that actually runs OCR/
  extraction -- see `app.models.import_staging.ImportJob`'s own
  docstring for why a BackgroundTask alone could never survive a Render
  web-service restart mid-run.
- `import_batches.notes` / `.archived_at` support the new batch
  lifecycle (rename/delete/archive) -- see `app.services.
  import_queue_service.compute_batch_lifecycle_status`.
- `imported_documents.storage_bucket` / `.storage_key` record where a
  document's original bytes durably live (Supabase Storage, or a local
  fallback -- see `app.core.document_storage`) -- both nullable, and
  every existing row is left with `original_path` as its sole location
  reference, exactly as before this migration.

Hand-written (not raw `alembic revision --autogenerate` output) for the
same reason 0316ad9e1d33 was: autogenerate against this project's SQLite
dev database proposes a long list of unrelated index/type "changes" that
are just dialect-reflection noise, not real schema differences. Only the
genuinely new objects below are included.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a1c9e2f5b3d'
down_revision: Union[str, Sequence[str], None] = '0316ad9e1d33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('import_batches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('archived_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('imported_documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('storage_bucket', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('storage_key', sa.Text(), nullable=True))

    op.create_table(
        'import_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=True),
        sa.Column('imported_document_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('worker_id', sa.String(length=120), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['batch_id'], ['import_batches.id'], name='fk_import_jobs_batch_id_import_batches'),
        sa.ForeignKeyConstraint(
            ['imported_document_id'],
            ['imported_documents.id'],
            name='fk_import_jobs_imported_document_id_imported_documents',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('imported_document_id', name='uq_import_jobs_imported_document_id'),
    )
    op.create_index(op.f('ix_import_jobs_batch_id'), 'import_jobs', ['batch_id'], unique=False)
    op.create_index(op.f('ix_import_jobs_imported_document_id'), 'import_jobs', ['imported_document_id'], unique=False)
    op.create_index(op.f('ix_import_jobs_status'), 'import_jobs', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_import_jobs_status'), table_name='import_jobs')
    op.drop_index(op.f('ix_import_jobs_imported_document_id'), table_name='import_jobs')
    op.drop_index(op.f('ix_import_jobs_batch_id'), table_name='import_jobs')
    op.drop_table('import_jobs')

    with op.batch_alter_table('imported_documents', schema=None) as batch_op:
        batch_op.drop_column('storage_key')
        batch_op.drop_column('storage_bucket')

    with op.batch_alter_table('import_batches', schema=None) as batch_op:
        batch_op.drop_column('archived_at')
        batch_op.drop_column('notes')
