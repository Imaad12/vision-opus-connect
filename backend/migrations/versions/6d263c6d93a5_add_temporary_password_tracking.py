"""add temporary password tracking to app_users

Revision ID: 6d263c6d93a5
Revises: 9762f7169d40
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d263c6d93a5'
down_revision: Union[str, Sequence[str], None] = '9762f7169d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # `must_change_password`: true whenever the account's current password
    # was set by an admin (creation, or an admin-triggered reset) rather
    # than chosen by the account holder themselves -- the login flow
    # forces a password-set screen before anything else in the ERP while
    # this is true (see src/routes/_authenticated/route.tsx). Defaults
    # true on new rows: a fresh account only ever starts with an
    # admin-generated temporary password (see user_service.create_user).
    #
    # `password_changed_at`: set only when the account holder sets their
    # own password (first-login or self-service change) -- an admin
    # create/reset deliberately does NOT touch it, so it stays a genuine
    # "the human last changed this, not an admin" signal, not just "the
    # password last changed."
    with op.batch_alter_table('app_users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'must_change_password',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column('password_changed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('app_users', schema=None) as batch_op:
        batch_op.drop_column('password_changed_at')
        batch_op.drop_column('must_change_password')
