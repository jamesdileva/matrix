"""checkpoints table

Revision ID: c5d8e1b2049f
Revises: b2f4a7c91d58
Create Date: 2026-10-08 13:02:51.884120

S12: a resumable snapshot of a run's transmission state. Small rows,
written every N generations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5d8e1b2049f'
down_revision: Union[str, None] = 'b2f4a7c91d58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'checkpoints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('experiment_id', sa.Integer(), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('state', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_checkpoints_experiment_generation', 'checkpoints', ['experiment_id', 'generation']
    )


def downgrade() -> None:
    op.drop_index('ix_checkpoints_experiment_generation', table_name='checkpoints')
    op.drop_table('checkpoints')
