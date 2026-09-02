"""link app_users to employees

Revision ID: 9762f7169d40
Revises: 82e3dcd132c3
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9762f7169d40'
down_revision: Union[str, Sequence[str], None] = '82e3dcd132c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable: not every VINCO login corresponds to an HR roster entry
    # (e.g. a system/admin account), and not every employee needs one.
    # Unique: at most one VINCO login per employee -- this is the
    # constraint that lets "does this employee have a VINCO login"
    # be answered by a single indexed lookup, and prevents two admins
    # racing to provision the same employee twice.
    with op.batch_alter_table('app_users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('employee_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_app_users_employee', 'employees', ['employee_id'], ['id']
        )
        batch_op.create_unique_constraint('uq_app_users_employee_id', ['employee_id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('app_users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_app_users_employee_id', type_='unique')
        batch_op.drop_constraint('fk_app_users_employee', type_='foreignkey')
        batch_op.drop_column('employee_id')
