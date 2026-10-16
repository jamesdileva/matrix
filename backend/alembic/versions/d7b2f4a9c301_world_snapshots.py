"""world snapshots table

Revision ID: d7b2f4a9c301
Revises: c5d8e1b2049f
Create Date: 2026-10-12 21:14:03.118204

S38: the whole world as one row - a save, an autosave, or an archive.
A snapshot is the world's serialized state, so recovery and resume are
one query away.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b2f4a9c301'
down_revision: Union[str, None] = 'c5d8e1b2049f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'world_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('world_id', sa.Integer(), nullable=False),
        sa.Column('tick', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_world_snapshots_world_tick', 'world_snapshots', ['world_id', 'tick']
    )


def downgrade() -> None:
    op.drop_index('ix_world_snapshots_world_tick', table_name='world_snapshots')
    op.drop_table('world_snapshots')