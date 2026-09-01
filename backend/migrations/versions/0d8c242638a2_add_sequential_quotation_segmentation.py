"""add sequential quotation segmentation

Revision ID: 0d8c242638a2
Revises: 1cbbf15aef72
Create Date: 2026-08-24 20:10:17.040986

Adds `imported_document_segments` (see `app.core.import_segmentation` and
`app.models.import_staging.ImportedDocumentSegment`) and the segment FKs on
`imported_quotation_candidates`/`imported_boq_line_candidates` a scanned
batch document's per-quotation page ranges need.

No migration step is needed for `ExtractionStatus.SEGMENTS_PROPOSED` or
the other new enum values used elsewhere in this change
(`SegmentReviewStatus`, `ImportAuditEventType.SEGMENTED`): every enum in
this schema is stored `native_enum=False` (a plain VARCHAR with no CHECK
constraint — confirmed by inspecting the live schema before writing this
migration), the same reason `ExtractionStatus.MULTIPLE_QUOTATIONS_DETECTED`
never needed one either.

`imported_quotation_candidates.imported_document_id` loses its UNIQUE
constraint: a segmented OCR document can now own more than one candidate
row (one per accepted segment), each individually made unique instead by
the new `imported_document_segment_id` column. SQLite has no native ALTER
for dropping an unnamed constraint, so this table is rebuilt via batch
mode using an explicit `copy_from` (the pre-migration column shape,
without the old unique constraint) rather than autogenerate's default
reflection-based recreate, which left the old constraint in place.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d8c242638a2'
down_revision: Union[str, Sequence[str], None] = '1cbbf15aef72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _quotation_candidates_columns_without_segment_fk() -> sa.Table:
    """The `imported_quotation_candidates` column shape as it exists
    *before* this migration (unique `imported_document_id`, no segment
    columns) — used as `copy_from` for both directions' batch rebuild, so
    SQLite's table recreation starts from the actual old shape rather than
    a live reflection that would silently keep the constraint this
    migration means to drop."""
    metadata = sa.MetaData()
    return sa.Table(
        "imported_quotation_candidates",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("imported_document_id", sa.Integer(), sa.ForeignKey("imported_documents.id"), nullable=False),
        sa.Column("quotation_number", sa.String(length=100)),
        sa.Column("quotation_date", sa.Date()),
        sa.Column("client_name", sa.String(length=255)),
        sa.Column("project_name", sa.String(length=255)),
        sa.Column("project_number", sa.String(length=50)),
        sa.Column("description", sa.Text()),
        sa.Column("currency", sa.String(length=10)),
        sa.Column("net_value", sa.Numeric(14, 2)),
        sa.Column("tax_value", sa.Numeric(14, 2)),
        sa.Column("gross_value", sa.Numeric(14, 2)),
        sa.Column("valid_until", sa.Date()),
        sa.Column("payment_terms", sa.String(length=255)),
        sa.Column("notes", sa.Text()),
        sa.Column("raw_values", sa.Text()),
        sa.Column("field_confidence", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'imported_document_segments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('imported_document_id', sa.Integer(), nullable=False),
        sa.Column('segment_order', sa.Integer(), nullable=False),
        sa.Column('start_page', sa.Integer(), nullable=False),
        sa.Column('end_page', sa.Integer(), nullable=False),
        sa.Column('boundary_confidence', sa.String(length=20), nullable=True),
        sa.Column('boundary_signals', sa.Text(), nullable=True),
        sa.Column('detected_quotation_number', sa.String(length=100), nullable=True),
        sa.Column('detected_quotation_date', sa.Date(), nullable=True),
        sa.Column(
            'review_status',
            sa.Enum(
                'PROPOSED', 'ACCEPTED', 'LOCKED', 'CONFIRMED', 'REJECTED', 'EXCLUDED_NOT_A_QUOTATION',
                name='segmentreviewstatus', native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column('reviewer_adjusted', sa.Boolean(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('resulting_client_id', sa.Integer(), nullable=True),
        sa.Column('resulting_project_id', sa.Integer(), nullable=True),
        sa.Column('resulting_quotation_id', sa.Integer(), nullable=True),
        sa.Column('resulting_quotation_version_id', sa.Integer(), nullable=True),
        sa.Column('resulting_boq_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['imported_document_id'], ['imported_documents.id'], ),
        sa.ForeignKeyConstraint(['resulting_boq_id'], ['boqs.id'], ),
        sa.ForeignKeyConstraint(['resulting_client_id'], ['clients.id'], ),
        sa.ForeignKeyConstraint(['resulting_project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['resulting_quotation_id'], ['quotations.id'], ),
        sa.ForeignKeyConstraint(['resulting_quotation_version_id'], ['quotation_versions.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('imported_boq_line_candidates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('imported_document_segment_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_ibqlc_segment', 'imported_document_segments', ['imported_document_segment_id'], ['id']
        )

    # Rebuilt from an explicit pre-migration column shape (not a live
    # reflection) so the old, unnamed UNIQUE(imported_document_id)
    # constraint is genuinely dropped rather than silently carried over --
    # see this module's docstring and
    # `_quotation_candidates_columns_without_segment_fk`.
    with op.batch_alter_table(
        'imported_quotation_candidates',
        schema=None,
        recreate='always',
        copy_from=_quotation_candidates_columns_without_segment_fk(),
    ) as batch_op:
        batch_op.add_column(sa.Column('imported_document_segment_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            'uq_imported_quotation_candidates_segment', ['imported_document_segment_id']
        )
        batch_op.create_foreign_key(
            'fk_iqc_segment', 'imported_document_segments', ['imported_document_segment_id'], ['id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imported_quotation_candidates', schema=None, recreate='always') as batch_op:
        batch_op.drop_constraint('fk_iqc_segment', type_='foreignkey')
        batch_op.drop_constraint('uq_imported_quotation_candidates_segment', type_='unique')
        batch_op.drop_column('imported_document_segment_id')
        batch_op.create_unique_constraint(
            'uq_imported_quotation_candidates_document', ['imported_document_id']
        )

    with op.batch_alter_table('imported_boq_line_candidates', schema=None) as batch_op:
        batch_op.drop_constraint('fk_ibqlc_segment', type_='foreignkey')
        batch_op.drop_column('imported_document_segment_id')

    op.drop_table('imported_document_segments')
