"""material target segment (1-6 campaign matrix)

Revision ID: a1f2c3d4e5f6
Revises: ba81baa50897
Create Date: 2026-10-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1f2c3d4e5f6'
down_revision = 'ba81baa50897'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('materials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('target_segment', sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('materials', schema=None) as batch_op:
        batch_op.drop_column('target_segment')
