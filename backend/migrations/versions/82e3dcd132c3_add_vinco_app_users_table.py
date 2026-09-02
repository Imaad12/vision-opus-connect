"""add vinco app_users table for native username/password login

Revision ID: 82e3dcd132c3
Revises: 3ebcc85f8771
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82e3dcd132c3'
down_revision: Union[str, Sequence[str], None] = '3ebcc85f8771'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'app_users',
        # Supabase Auth's real user id (a UUID), stored as opaque text --
        # not a FK, matching this schema's existing convention for
        # referencing a Supabase auth user id (see Lead.owner_id):
        # auth.users lives in Supabase's own schema, not vinco.
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        # server_default as a real boolean literal ('true'/'false'), not
        # an integer -- see 125d4e231e60's own fix for why an integer
        # literal here is valid SQLite DDL but a Postgres DatatypeMismatch.
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('app_users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_app_users_username'), ['username'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('app_users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_app_users_username'))

    op.drop_table('app_users')
