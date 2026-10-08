"""agent local id

Revision ID: a1c9e2f47b03
Revises: 4e0df830e730
Create Date: 2026-10-08 09:12:44.118203

The engine numbers agents per world (1..N); AgentModel.id is a global
row id that parent_id FKs reference. S09 stores the per-world id
alongside so a world's engine ids map onto their database rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9e2f47b03'
down_revision: Union[str, None] = '4e0df830e730'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('local_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_agents_world_local', ['world_id', 'local_id'])


def downgrade() -> None:
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_index('ix_agents_world_local')
        batch_op.drop_column('local_id')
