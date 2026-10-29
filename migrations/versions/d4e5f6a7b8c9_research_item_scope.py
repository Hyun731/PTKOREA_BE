"""research item scope (팩트북 조사 범위 항목)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('research_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scope_id', sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('research_items', schema=None) as batch_op:
        batch_op.drop_column('scope_id')
