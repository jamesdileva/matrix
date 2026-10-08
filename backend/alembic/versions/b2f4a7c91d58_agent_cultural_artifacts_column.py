"""agent cultural artifacts column

Revision ID: b2f4a7c91d58
Revises: a1c9e2f47b03
Create Date: 2026-10-08 10:41:07.553210

S10's inheritance package carries cultural artifacts; the agents table
stores two of the other three parts already, so the fourth gets a
column rather than being folded into something it is not.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2f4a7c91d58'
down_revision: Union[str, None] = 'a1c9e2f47b03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cultural_artifacts', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_column('cultural_artifacts')
